"""AppController: the single owner of lighting state, threads and devices.

GUI code calls only this class (never hidapi/dxcam directly). All public
methods are thread-safe; the GUI polls :meth:`snapshot` on a timer.

Threads owned here:
* DeviceWorker   - the only thread that talks HID,
* ScreenSyncEngine - capture + analysis (when screen sync is active),
* EffectRunner   - software effects (when such an effect is active),
* AutomationService - optional profile rules.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional

from ..capture import Region
from ..device import protocol as P
from ..device.conflicts import ConflictReport, detect_conflicts
from ..device.driver import HardwareEffect
from ..device.mock import MockBackend
from ..device.transport import DeviceBackend, HidapiBackend
from ..device.worker import DeviceSnapshot, DeviceWorker, WorkerConfig
from ..effects import EffectConfig, render, to_hardware
from ..effects.runner import EffectRunner
from ..profiles.model import LightMode, Profile, StaticState, SyncProfile
from ..profiles.store import ProfileStore
from ..rgb import BLACK, RGB, ZoneColors, uniform
from ..sync.engine import ScreenSyncEngine, SyncConfig, SyncStats
from ..sync.output import scale_zone_colors
from .settings import PERFORMANCE_PRESETS, AppSettings, SettingsStore

log = logging.getLogger(__name__)

HISTORY_LIMIT = 20
RESTART_BUDGET = 5  # automatic restarts per 5 minutes per component


class Mode(str, Enum):
    OFF = "off"
    STATIC = "static"
    EFFECT = "effect"
    SCREEN_SYNC = "screen_sync"


@dataclass
class LightingState:
    mode: Mode = Mode.STATIC
    static: StaticState = field(default_factory=StaticState)
    effect: EffectConfig = field(default_factory=EffectConfig)
    sync: SyncProfile = field(default_factory=SyncProfile)
    master_brightness: int = 100
    power: bool = True
    profile_id: Optional[str] = None
    profile_name: str = ""

    def clone(self) -> "LightingState":
        return LightingState(
            self.mode,
            StaticState(list(self.static.zone_colors), list(self.static.zone_brightness)),
            EffectConfig.from_dict(self.effect.to_dict()),
            SyncProfile.from_dict(self.sync.to_dict()),
            self.master_brightness,
            self.power,
            self.profile_id,
            self.profile_name,
        )


@dataclass(frozen=True)
class AppSnapshot:
    mode: Mode
    power: bool
    profile_id: Optional[str]
    profile_name: str
    intended: Optional[ZoneColors]  # what the app wants the keyboard to show now
    intended_kind: str  # static | software | hardware_effect | screen_sync | off
    simulated: bool  # intended colours are a *simulation* of a native effect
    hardware_effect: Optional[HardwareEffect]
    device: DeviceSnapshot
    sync: Optional[SyncStats]
    effect: EffectConfig
    static: StaticState
    master_brightness: int
    conflict: ConflictReport
    automation_rule: Optional[str]
    can_undo: bool
    simulation_backend: bool  # device layer runs on the mock (hardware access disabled)
    cpu_percent: float
    memory_mb: float


class _RestartBudget:
    def __init__(self, limit: int = RESTART_BUDGET, window: float = 300.0) -> None:
        self.limit, self.window = limit, window
        self.events: list[float] = []

    def allow(self) -> bool:
        now = time.perf_counter()
        self.events = [t for t in self.events if now - t < self.window]
        if len(self.events) >= self.limit:
            return False
        self.events.append(now)
        return True


class AppController:
    def __init__(
        self,
        settings: SettingsStore,
        profiles: ProfileStore,
        backend_factory: Callable[[], DeviceBackend] | None = None,
        sync_engine_factory: Callable[[Callable[[ZoneColors], None]], ScreenSyncEngine] | None = None,
        conflict_fn: Callable[[], ConflictReport] = detect_conflicts,
        simulated: bool = False,
    ) -> None:
        self.settings_store = settings
        self.profiles = profiles
        self._custom_backend_factory = backend_factory
        self._forced_simulation = simulated
        self._sync_engine_factory = sync_engine_factory or (lambda sink: ScreenSyncEngine(sink))
        self._conflict_fn = conflict_fn
        self._lock = threading.RLock()
        self._state = LightingState()
        self._history: list[LightingState] = []
        self._last_history_push = 0.0
        self._intended: Optional[ZoneColors] = None
        self._intended_kind = "static"
        self._hw_effect: Optional[HardwareEffect] = None
        self._effect_t0 = time.perf_counter()
        self._runner: Optional[EffectRunner] = None
        self._engine: Optional[ScreenSyncEngine] = None
        self._conflict = ConflictReport((), (), checked=False)
        self._automation = None
        self._automation_prev_profile: Optional[str] = None
        self._automation_applied_profile: Optional[str] = None
        self._budget_sync, self._budget_effect, self._budget_device = _RestartBudget(), _RestartBudget(), _RestartBudget()
        self._proc_stats = (0.0, 0.0, 0.0)  # timestamp, cpu, mem
        self._psutil_proc = None
        self._started = False
        self.worker = self._make_worker()

    # ---------------------------------------------------------- properties
    @property
    def settings(self) -> AppSettings:
        return self.settings_store.settings

    @property
    def simulation(self) -> bool:
        """True when no real HID device is written (UI must say so)."""
        if self._forced_simulation:
            return True
        return self._custom_backend_factory is None and not self.settings.hardware_enabled

    def _backend_factory(self) -> Callable[[], DeviceBackend]:
        if self._custom_backend_factory is not None:
            return self._custom_backend_factory
        if self.settings.hardware_enabled:
            return HidapiBackend
        shared = MockBackend()
        return lambda: shared

    def _make_worker(self) -> DeviceWorker:
        s = self.settings
        self._worker_simulated = self.simulation
        cfg = WorkerConfig(
            update_hz=s.update_hz,
            ack_read=s.ack_read,
            refresh_interval_s=s.refresh_interval_s,
            trace_packets=s.debug_logging,
        )
        return DeviceWorker(self._backend_factory(), cfg)

    # ----------------------------------------------------------- lifecycle
    def start(self, apply_startup_profile: bool = True) -> None:
        if self._started:
            return
        self._started = True
        self.worker.start()
        self.refresh_conflicts()
        if apply_startup_profile:
            self._apply_startup_profile()
        self.configure_automation()

    def _apply_startup_profile(self) -> None:
        s = self.settings
        pid: Optional[str]
        if s.startup_profile == "none":
            return
        if s.startup_profile == "last":
            pid = s.last_profile_id or s.default_profile_id
        else:
            pid = s.startup_profile
        prof = self.profiles.get(pid) if pid else None
        if prof is None and s.default_profile_id:
            prof = self.profiles.get(s.default_profile_id)
        if prof is not None:
            self.apply_profile(prof.id, source="startup")

    def shutdown(self, timeout: float = 3.0) -> None:
        log.info("Shutting down (exit action: %s)", self.settings.exit_action)
        if self._automation is not None:
            self._automation.stop()
            self._automation = None
        self._stop_sources()
        action = self.settings.exit_action
        try:
            if action == "off":
                self.worker.submit_colors(uniform(BLACK), "exit")
            elif action == "restore":
                restore = self._exit_restore_state()
                if restore is not None:
                    self._submit_static_for(restore)
            if action != "keep":
                self.worker.wait_idle(1.5)
        except Exception:  # pragma: no cover
            log.exception("exit action failed")
        self.worker.stop(timeout)
        self._started = False

    def _exit_restore_state(self) -> Optional[LightingState]:
        """The last manual (non screen-sync) profile, so the keyboard does not
        stay frozen on the last screen colour after exit."""
        pid = self.settings.last_manual_profile_id
        prof = self.profiles.get(pid) if pid else None
        if prof is not None and prof.mode in (LightMode.STATIC, LightMode.EFFECT):
            st = self._state_from_profile(prof)
            return st
        with self._lock:
            st = self._state.clone()
            if st.mode == Mode.SCREEN_SYNC:
                # no manual profile known: fall back to the app's own static
                # colours rather than leaving the last screen colour frozen
                st.mode = Mode.STATIC
            return st

    def _submit_static_for(self, st: LightingState) -> None:
        if not st.power:
            self.worker.submit_colors(uniform(BLACK), "exit")
            return
        if st.mode == Mode.EFFECT:
            hw = self._hardware_for(st)
            if hw is not None:
                self.worker.submit_effect(hw, "exit")
                return
            colors = render(st.effect, 0.0)
        else:
            colors = self._static_colors(st)
        self.worker.submit_colors(scale_zone_colors(colors, st.master_brightness / 100.0), "exit")

    # -------------------------------------------------------------- history
    def _push_history(self, coalesce: bool = False) -> None:
        now = time.perf_counter()
        if coalesce and now - self._last_history_push < 1.5:
            return
        self._last_history_push = now
        self._history.append(self._state.clone())
        del self._history[:-HISTORY_LIMIT]

    def undo(self) -> bool:
        with self._lock:
            if not self._history:
                return False
            prev = self._history.pop()
            self._activate(prev, push=False)
            return True

    # ------------------------------------------------------- state machine
    def _stop_sources(self) -> None:
        if self._runner is not None:
            self._runner.stop()
            self._runner = None
        if self._engine is not None:
            self._engine.stop()
            self._engine = None
        self._hw_effect = None

    def _static_colors(self, st: LightingState) -> ZoneColors:
        cols = st.static.zone_colors
        br = st.static.zone_brightness
        return scale_zone_colors(tuple(cols), tuple(b / 100.0 for b in br))  # type: ignore[arg-type]

    def _hardware_for(self, st: LightingState) -> Optional[HardwareEffect]:
        hw = to_hardware(st.effect)
        if hw is None:
            return None
        k = st.master_brightness / 100.0
        if k < 1.0:
            hw = replace(hw, colors=tuple(scale_zone_colors((c, c, c, c), k)[0] for c in hw.colors))
        return hw

    def _submit(self, colors: ZoneColors, kind: str, source: str) -> None:
        """Common output path: master brightness + power, then the worker."""
        st = self._state
        out = uniform(BLACK) if not st.power else scale_zone_colors(colors, st.master_brightness / 100.0)
        self._intended = out
        self._intended_kind = "off" if not st.power else kind
        self.worker.submit_colors(out, source)

    def _activate(self, st: LightingState, push: bool = True) -> None:
        with self._lock:
            if push:
                self._push_history()
            old_mode = self._state.mode
            self._state = st
            needs_restart = True
            if old_mode == Mode.SCREEN_SYNC and st.mode == Mode.SCREEN_SYNC and self._engine is not None:
                needs_restart = False
            if needs_restart:
                self._stop_sources()
            if not st.power or st.mode == Mode.OFF:
                self._stop_sources()
                self._submit(uniform(BLACK), "off", "power")
                return
            if st.mode == Mode.STATIC:
                self._submit(self._static_colors(st), "static", "static")
            elif st.mode == Mode.EFFECT:
                self._effect_t0 = time.perf_counter()
                hw = self._hardware_for(st)
                if hw is not None:
                    self._hw_effect = hw
                    self._intended_kind = "hardware_effect"
                    self._intended = None
                    self.worker.submit_effect(hw, f"effect:{st.effect.effect.value}")
                else:
                    cfg = st.effect
                    self._runner = EffectRunner(lambda t: render(cfg, t), lambda c: self._submit(c, "software", "effect"))
                    self._runner.start()
            elif st.mode == Mode.SCREEN_SYNC:
                cfg = self._sync_config(st.sync)
                if self._engine is None:
                    self._engine = self._sync_engine_factory(self._on_sync_colors)
                    self._engine.start(cfg)
                else:
                    self._engine.update_config(cfg)
                self.worker.set_update_rate(min(self.settings.update_hz, PERFORMANCE_PRESETS[st.sync.performance]["update_hz"]))
                return
            self.worker.set_update_rate(self.settings.update_hz)

    def _on_sync_colors(self, colors: ZoneColors) -> None:
        if self._state.mode == Mode.SCREEN_SYNC:
            self._submit(colors, "screen_sync", "screen_sync")

    def _sync_config(self, sp: SyncProfile) -> SyncConfig:
        s = self.settings
        perf = PERFORMANCE_PRESETS.get(sp.performance, PERFORMANCE_PRESETS["balanced"])
        return SyncConfig(
            monitor_id=s.monitor_id,
            backend=s.capture_backend,
            region=Region(*s.region),
            analysis=sp.analysis,
            transition=sp.transition,
            output=sp.output,
            analysis_fps=perf["analysis_fps"],
            output_hz=perf["output_hz"],
            hdr_compensation=s.hdr_compensation,
        )

    def _current(self) -> LightingState:
        return self._state.clone()

    # ----------------------------------------------------------- manual RGB
    def set_static(
        self,
        zone_colors: list[RGB] | None = None,
        zone_brightness: list[int] | None = None,
        master_brightness: int | None = None,
    ) -> None:
        with self._lock:
            st = self._current()
            st.mode = Mode.STATIC
            st.power = True
            if zone_colors is not None:
                st.static.zone_colors = [tuple(c) for c in zone_colors]  # type: ignore[misc]
            if zone_brightness is not None:
                st.static.zone_brightness = [int(min(max(b, 0), 100)) for b in zone_brightness]
            if master_brightness is not None:
                st.master_brightness = int(min(max(master_brightness, 0), 100))
            st.profile_id, st.profile_name = None, ""
            self._push_history(coalesce=self._state.mode == Mode.STATIC)
            self._activate(st, push=False)

    def set_zone_color(self, zones: list[int], color: RGB) -> None:
        with self._lock:
            cols = list(self._state.static.zone_colors)
            for z in zones:
                if 0 <= z < 4:
                    cols[z] = tuple(color)  # type: ignore[call-overload]
            self.set_static(zone_colors=cols)

    def set_all(self, color: RGB) -> None:
        self.set_zone_color([0, 1, 2, 3], color)

    def set_master_brightness(self, value: int) -> None:
        with self._lock:
            st = self._current()
            st.master_brightness = int(min(max(value, 0), 100))
            self._push_history(coalesce=True)
            self._state.master_brightness = st.master_brightness
            if st.mode == Mode.EFFECT or not st.power:
                self._activate(st, push=False)
            elif st.mode == Mode.STATIC:
                self._submit(self._static_colors(st), "static", "brightness")
            # screen sync / software effects pick it up on the next frame

    def set_power(self, on: bool) -> None:
        with self._lock:
            st = self._current()
            st.power = bool(on)
            if on and st.mode == Mode.OFF:
                st.mode = Mode.STATIC
            self._activate(st)

    # ------------------------------------------------------------- effects
    def start_effect(self, cfg: EffectConfig) -> None:
        with self._lock:
            st = self._current()
            st.mode, st.power = Mode.EFFECT, True
            st.effect = EffectConfig.from_dict(cfg.to_dict())
            st.profile_id, st.profile_name = None, ""
            self._activate(st)

    def stop_effect(self) -> None:
        with self._lock:
            if self._state.mode != Mode.EFFECT:
                return
            st = self._current()
            st.mode = Mode.STATIC
            self._activate(st)

    # --------------------------------------------------------- screen sync
    def start_sync(self, sync: SyncProfile | None = None) -> None:
        with self._lock:
            st = self._current()
            st.mode, st.power = Mode.SCREEN_SYNC, True
            if sync is not None:
                st.sync = SyncProfile.from_dict(sync.to_dict())
            self._activate(st)

    def update_sync(self, sync: SyncProfile) -> None:
        with self._lock:
            self._state.sync = SyncProfile.from_dict(sync.to_dict())
            if self._state.mode == Mode.SCREEN_SYNC and self._engine is not None:
                self._engine.update_config(self._sync_config(self._state.sync))
                self.worker.set_update_rate(
                    min(self.settings.update_hz, PERFORMANCE_PRESETS[self._state.sync.performance]["update_hz"])
                )

    def stop_sync(self) -> None:
        with self._lock:
            if self._state.mode != Mode.SCREEN_SYNC:
                return
            restore = self._exit_restore_state()
            st = restore if restore is not None else self._current()
            if st.mode == Mode.SCREEN_SYNC:
                st.mode = Mode.STATIC
            self._activate(st)

    def toggle_sync(self) -> None:
        if self._state.mode == Mode.SCREEN_SYNC:
            self.stop_sync()
        else:
            self.start_sync()

    def sync_preview(self):
        eng = self._engine
        return eng.preview() if eng is not None else (None, (0, 0, 0, 0))

    def apply_capture_settings(self) -> None:
        """Monitor/backend/region/performance changed in settings."""
        with self._lock:
            if self._engine is not None and self._state.mode == Mode.SCREEN_SYNC:
                self._engine.update_config(self._sync_config(self._state.sync))

    # ------------------------------------------------------------ profiles
    def _state_from_profile(self, prof: Profile) -> LightingState:
        mode = {LightMode.STATIC: Mode.STATIC, LightMode.EFFECT: Mode.EFFECT, LightMode.SCREEN_SYNC: Mode.SCREEN_SYNC, LightMode.OFF: Mode.OFF}[prof.mode]
        return LightingState(
            mode=mode,
            static=StaticState(list(prof.static.zone_colors), list(prof.static.zone_brightness)),
            effect=EffectConfig.from_dict(prof.effect.to_dict()),
            sync=SyncProfile.from_dict(prof.sync.to_dict()),
            master_brightness=prof.master_brightness,
            power=prof.mode != LightMode.OFF,
            profile_id=prof.id,
            profile_name=prof.name,
        )

    def apply_profile(self, pid: str, source: str = "user") -> bool:
        prof = self.profiles.get(pid)
        if prof is None:
            log.warning("apply_profile: unknown id %s", pid)
            return False
        with self._lock:
            if source == "user":
                self._automation_applied_profile = None
            self._activate(self._state_from_profile(prof))
        s = self.settings
        recent = [pid] + [p for p in s.recent_profiles if p != pid]
        changes: dict = {"recent_profiles": recent[:6], "last_profile_id": pid}
        if prof.mode in (LightMode.STATIC, LightMode.EFFECT):
            changes["last_manual_profile_id"] = pid
        try:
            self.settings_store.update(**changes)
        except OSError:  # pragma: no cover
            log.exception("could not persist recent profiles")
        log.info("Profile applied: %s (%s)", prof.name, source)
        return True

    def current_as_profile(self, name: str, pid: str | None = None) -> Profile:
        from ..profiles.model import new_id

        with self._lock:
            st = self._state
            mode = {Mode.STATIC: LightMode.STATIC, Mode.EFFECT: LightMode.EFFECT, Mode.SCREEN_SYNC: LightMode.SCREEN_SYNC, Mode.OFF: LightMode.OFF}[st.mode]
            if not st.power:
                mode = LightMode.OFF
            return Profile(
                id=pid or new_id(),
                name=name,
                mode=mode,
                master_brightness=st.master_brightness,
                static=StaticState(list(st.static.zone_colors), list(st.static.zone_brightness)),
                effect=EffectConfig.from_dict(st.effect.to_dict()),
                sync=SyncProfile.from_dict(st.sync.to_dict()),
            )

    # ----------------------------------------------------------- automation
    def configure_automation(self) -> None:
        from ..automation import AutomationService

        if self._automation is not None:
            self._automation.stop()
            self._automation = None
        if not self.settings.automation_enabled or not self.settings.automation:
            return
        self._automation = AutomationService(lambda: list(self.settings.automation), self._on_rule_apply, self._on_rule_revert)
        self._automation.start()

    def _on_rule_apply(self, pid: str, rule_id: str) -> None:
        with self._lock:
            if self._automation_applied_profile is None:
                self._automation_prev_profile = self._state.profile_id
            self._automation_applied_profile = pid
        self.apply_profile(pid, source=f"rule:{rule_id}")

    def _on_rule_revert(self, rule_id: str) -> None:
        with self._lock:
            applied, prev = self._automation_applied_profile, self._automation_prev_profile
            self._automation_applied_profile = None
            # only revert if the user did not pick something else meanwhile
            if applied is None or self._state.profile_id != applied:
                return
        if prev:
            self.apply_profile(prev, source=f"revert:{rule_id}")
        elif self._state.mode == Mode.SCREEN_SYNC:
            self.stop_sync()

    # ---------------------------------------------------- settings changes
    def apply_device_settings(self) -> None:
        """Update rate / ack / refresh / hardware toggle changed."""
        s = self.settings
        rebuild = (
            self.simulation != self._worker_simulated
            or self.worker.config.ack_read != s.ack_read
            or self.worker.config.trace_packets != s.debug_logging
        )
        if rebuild:
            self.restart_device()
        else:
            self.worker.config.refresh_interval_s = s.refresh_interval_s
            self.worker.set_update_rate(s.update_hz)

    def restart_device(self) -> None:
        with self._lock:
            self.worker.stop()
            self.worker = self._make_worker()
            self.worker.start()
            self._activate(self._state.clone(), push=False)

    def reconnect(self) -> None:
        self.worker.request_reconnect()

    def refresh_conflicts(self) -> ConflictReport:
        try:
            self._conflict = self._conflict_fn()
        except Exception:  # pragma: no cover
            log.exception("conflict detection failed")
        return self._conflict

    # ------------------------------------------------------- system events
    def on_suspend(self) -> None:
        log.info("System suspend: pausing capture and closing HID")
        if self._engine is not None:
            self._engine.pause()
        if self._runner is not None:
            self._runner.stop()
        self.worker.suspend()

    def on_resume(self) -> None:
        log.info("System resume: reconnecting")
        self.worker.resume()
        with self._lock:
            if self._state.mode == Mode.EFFECT and self._hw_effect is None:
                self._activate(self._state.clone(), push=False)
        if self._engine is not None:
            self._engine.resume()

    def on_display_off(self) -> None:
        """Console display turned off - on Modern Standby (S0ix) laptops this is
        the only reliable "going to sleep" signal (no PBT_APMSUSPEND)."""
        log.info("Display off: pausing capture")
        if self._engine is not None:
            self._engine.pause()

    def on_display_on(self) -> None:
        """Display back on (wake from Modern Standby): the MCU may have lost
        its state, so re-assert the colours and resume capture."""
        log.info("Display on: resuming capture and re-asserting colours")
        self.worker.invalidate()
        if self._engine is not None:
            self._engine.resume()

    def on_session_lock(self) -> None:
        log.info("Session locked: pausing capture")
        if self._engine is not None:
            self._engine.pause()

    def on_session_unlock(self) -> None:
        log.info("Session unlocked: resuming capture and re-asserting colours")
        if self._engine is not None:
            self._engine.resume()
        self.worker.invalidate()  # re-assert colours (another session may have changed them)

    # --------------------------------------------------------- supervision
    def watchdog(self) -> list[str]:
        """Restart crashed workers (bounded). Returns a list of actions."""
        actions: list[str] = []
        if not self.settings.auto_recovery:
            return actions
        with self._lock:
            if self._started and not self.worker.alive and self._budget_device.allow():
                log.error("DeviceWorker not alive - recreating")
                self.worker = self._make_worker()
                self.worker.start()
                self._activate(self._state.clone(), push=False)
                actions.append("device")
            st = self._state
            if st.mode == Mode.SCREEN_SYNC and st.power and self._engine is not None and not self._engine.running:
                if self._budget_sync.allow():
                    log.error("ScreenSync engine died - restarting")
                    self._engine = self._sync_engine_factory(self._on_sync_colors)
                    self._engine.start(self._sync_config(st.sync))
                    actions.append("sync")
            if st.mode == Mode.EFFECT and self._runner is not None and not self._runner.alive:
                if self._budget_effect.allow():
                    log.error("Effect runner died - restarting")
                    self._activate(st.clone(), push=False)
                    actions.append("effect")
        return actions

    # ------------------------------------------------------------- snapshot
    def _process_stats(self) -> tuple[float, float]:
        now = time.perf_counter()
        ts, cpu, mem = self._proc_stats
        if now - ts < 1.0:
            return cpu, mem
        try:
            import psutil

            if self._psutil_proc is None:
                self._psutil_proc = psutil.Process()
                self._psutil_proc.cpu_percent(None)
            cpu = self._psutil_proc.cpu_percent(None) / (psutil.cpu_count() or 1)
            mem = self._psutil_proc.memory_info().rss / (1024 * 1024)
        except Exception:  # pragma: no cover
            pass
        self._proc_stats = (now, cpu, mem)
        return cpu, mem

    def snapshot(self) -> AppSnapshot:
        with self._lock:
            st = self._state
            intended = self._intended
            simulated = False
            kind = self._intended_kind
            if kind == "hardware_effect" and st.power:
                k = st.master_brightness / 100.0
                intended = scale_zone_colors(render(st.effect, time.perf_counter() - self._effect_t0), k)
                simulated = True
            cpu, mem = self._process_stats()
            return AppSnapshot(
                mode=st.mode if st.power else Mode.OFF,
                power=st.power,
                profile_id=st.profile_id,
                profile_name=st.profile_name,
                intended=intended,
                intended_kind=kind,
                simulated=simulated,
                hardware_effect=self._hw_effect,
                device=self.worker.snapshot(),
                sync=self._engine.snapshot() if self._engine is not None else None,
                effect=st.effect,
                static=st.static,
                master_brightness=st.master_brightness,
                conflict=self._conflict,
                automation_rule=self._automation.active_rule if self._automation else None,
                can_undo=bool(self._history),
                simulation_backend=self.simulation,
                cpu_percent=cpu,
                memory_mb=mem,
            )

    @property
    def state(self) -> LightingState:
        with self._lock:
            return self._state.clone()

    @staticmethod
    def zone_mask_for(zones: list[int]) -> int:
        return P.mask_for_zones(zones)
