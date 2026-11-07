"""ScreenSyncEngine: capture -> analyse -> transition -> output, on its own thread.

Capture/analysis rate (``analysis_fps``) and the internal transition tick
(``output_hz``) are independent from the HID update rate, which the
DeviceWorker enforces. Nothing captured is ever written to disk or sent
anywhere: frames live in memory only (the GUI may show the tiny analysis
frame as a preview).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np

from ..capture import AUTO_ORDER, CaptureAccessLost, CaptureBackend, CaptureError, CaptureUnavailable, MonitorGone, MonitorInfo, Region, create_backend
from ..color.colorspace import oklab_to_rgb
from ..color.extractors import ColorAnalyzer
from ..color.frame import LetterboxTracker, compute_features
from ..color.scene import SceneCutDetector, signature
from ..color.settings import AnalysisSettings, OutputSettings, TransitionSettings
from ..device.ratelimit import RateMeter, backoff_delay
from ..rgb import ZoneColors
from .output import OutputDeadband, finalize
from .transition import TransitionEngine

log = logging.getLogger(__name__)

BLACK_FRAME_WARN_S = 3.0
HDR_SATURATION_BOOST = 1.2


@dataclass
class SyncConfig:
    monitor_id: Optional[str] = None
    backend: str = "auto"
    region: Region = field(default_factory=Region)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    transition: TransitionSettings = field(default_factory=TransitionSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    analysis_fps: float = 15.0
    output_hz: float = 30.0
    hdr_compensation: bool = True


@dataclass
class SyncStats:
    running: bool = False
    state: str = "stopped"  # stopped | starting | running | paused | error | backoff
    backend: str = ""
    monitor: str = ""
    hdr_enabled: bool = False
    capture_fps: float = 0.0
    analysis_fps: float = 0.0
    capture_ms: float = 0.0
    analysis_ms: float = 0.0
    transition_ms: float = 0.0
    pipeline_ms: float = 0.0
    cpu_percent: float = 0.0
    frames_captured: int = 0
    frames_analyzed: int = 0
    frames_static: int = 0
    frames_no_change: int = 0
    frames_dropped: int = 0
    scene_cuts: int = 0
    swaps_prevented: int = 0
    deadband_suppressed: int = 0
    submissions: int = 0
    mode_label: str = ""
    crop: tuple[int, int, int, int] = (0, 0, 0, 0)
    targets: Optional[ZoneColors] = None
    output: Optional[ZoneColors] = None
    palette: tuple[tuple[tuple[int, int, int], float], ...] = ()
    last_error: str = ""
    error_code: str = ""
    warning: str = ""
    retry_in_s: float = 0.0


def _ema(old: float, new: float, a: float = 0.2) -> float:
    return new if old == 0 else old + a * (new - old)


class ScreenSyncEngine:
    #: on a fallback backend (auto mode), retry the preferred one this often
    PROMOTE_AFTER_S = 30.0

    def __init__(
        self,
        sink: Callable[[ZoneColors], None],
        monitors_fn: Callable[[], list[MonitorInfo]] | None = None,
        backend_factory: Callable[[str], CaptureBackend] = create_backend,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if monitors_fn is None:
            from ..capture.monitors import enumerate_monitors

            monitors_fn = enumerate_monitors
        self._sink = sink
        self._monitors_fn = monitors_fn
        self._backend_factory = backend_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._paused = False
        self._reopen = False
        self._config = SyncConfig()
        self._stats = SyncStats()
        self._thread: threading.Thread | None = None
        self._capture: CaptureBackend | None = None
        self._monitor: MonitorInfo | None = None
        self._preview: np.ndarray | None = None
        self._next_retry = 0.0
        self._errors = 0
        self._opened_index = 0
        self._opened_at = 0.0
        self._reset_pipeline()

    # ----------------------------------------------------------------- API
    def _reset_pipeline(self) -> None:
        cfg = self._config
        self._analyzer = ColorAnalyzer(cfg.analysis)
        self._transition = TransitionEngine(cfg.transition)
        self._letterbox = LetterboxTracker()
        self._cuts = SceneCutDetector()
        self._deadband = OutputDeadband(cfg.transition.min_color_difference)
        self._black_since: float | None = None
        self._capture_meter = RateMeter(2.0, self._clock)
        self._analysis_meter = RateMeter(2.0, self._clock)
        self._last_analysis = -1e9
        self._last_new_frame = self._clock()

    def start(self, config: SyncConfig | None = None) -> None:
        if config is not None:
            with self._lock:
                self._config = config
        if self.running:
            return
        with self._lock:
            self._reset_pipeline()
            self._stats = SyncStats(running=True, state="starting")
            self._stop.clear()
            self._paused = False
            self._next_retry = 0.0
            self._errors = 0
        self._thread = threading.Thread(target=self._run, name="ScreenSync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> bool:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None:
            t.join(timeout)
        ok = not (t and t.is_alive())
        if ok:
            self._close_capture()
            with self._lock:
                self._stats = replace(self._stats, running=False, state="stopped")
        return ok

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def config(self) -> SyncConfig:
        with self._lock:
            return self._config

    def update_config(self, config: SyncConfig) -> None:
        with self._lock:
            old = self._config
            self._config = config
            capture_changed = (old.monitor_id, old.backend, old.region) != (config.monitor_id, config.backend, config.region)
            self._analyzer.settings = config.analysis
            self._transition.settings = config.transition
            self._deadband.min_diff = config.transition.min_color_difference
            if capture_changed:
                self._reopen = True
                self._next_retry = 0.0
                self._errors = 0
                self._letterbox.reset()
        self._wake.set()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
        self._wake.set()

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._reopen = True
            self._next_retry = 0.0
            self._errors = 0
        self._wake.set()

    def snapshot(self) -> SyncStats:
        with self._lock:
            st = replace(self._stats)
            if st.state == "backoff":
                st.retry_in_s = max(0.0, self._next_retry - self._clock())
            return st

    def preview(self) -> tuple[np.ndarray | None, tuple[int, int, int, int]]:
        with self._lock:
            return self._preview, self._stats.crop

    # -------------------------------------------------------------- thread
    def _run(self) -> None:
        wall0, cpu0 = time.perf_counter(), time.thread_time()
        try:
            while not self._stop.is_set():
                interval = self._tick()
                now_w, now_c = time.perf_counter(), time.thread_time()
                if now_w - wall0 >= 1.0:
                    with self._lock:
                        self._stats.cpu_percent = 100.0 * (now_c - cpu0) / (now_w - wall0)
                    wall0, cpu0 = now_w, now_c
                if interval > 0:
                    # Event.wait has ~15.6 ms granularity on Windows; short
                    # waits use the high-resolution time.sleep (Python 3.11+)
                    # so analysis/output rates are accurate.
                    if interval <= 0.06:
                        time.sleep(interval)
                    else:
                        self._wake.wait(interval)
                    self._wake.clear()
        except Exception as exc:  # pragma: no cover - safety net; watchdog restarts us
            log.exception("ScreenSync engine crashed")
            with self._lock:
                self._stats.state, self._stats.last_error, self._stats.error_code = "error", f"engine crashed: {exc}", "crash"
        finally:
            self._close_capture()

    def _close_capture(self) -> None:
        cap, self._capture = self._capture, None
        if cap is not None:
            try:
                cap.close()
            except Exception:  # pragma: no cover
                log.debug("capture close failed", exc_info=True)

    def _fail(self, exc: Exception, code: str) -> None:
        self._close_capture()
        self._errors += 1
        delay = backoff_delay(self._errors, 1.0, 30.0)
        if isinstance(exc, CaptureAccessLost):
            delay = min(delay, 5.0)  # lock screen / UAC: retry reasonably soon
        self._next_retry = self._clock() + delay
        with self._lock:
            self._stats.state = "backoff"
            self._stats.last_error = str(exc)
            self._stats.error_code = code
        log.warning("Capture problem (%s): %s - retry in %.0fs", code, exc, delay)

    def _open_capture(self) -> bool:
        cfg = self.config
        try:
            monitors = self._monitors_fn()
        except Exception as exc:  # pragma: no cover
            self._fail(exc, "monitors")
            return False
        from ..capture.monitors import find_monitor

        mon = find_monitor(monitors, cfg.monitor_id)
        if mon is None:
            self._fail(MonitorGone("No monitor found"), "monitor_gone")
            return False
        warning = ""
        if cfg.monitor_id and mon.id != cfg.monitor_id:
            warning = "monitor_fallback"
        auto = cfg.backend == "auto"
        names = AUTO_ORDER if auto else (cfg.backend,)
        last_exc: Exception | None = None
        for index, name in enumerate(names):
            try:
                cap = self._backend_factory(name)
                cap.open(mon, cfg.region)
            except CaptureAccessLost as exc:
                # Transient (wake from standby, lock screen, mode switch): do
                # NOT fall back to a slower backend, retry this one with backoff.
                log.info("capture backend %s temporarily unavailable: %s", name, exc)
                last_exc = exc
                break
            except CaptureError as exc:  # includes CaptureUnavailable
                log.info("capture backend %s failed: %s%s", name, exc, " - trying next" if auto else "")
                last_exc = exc
                continue
            except Exception as exc:  # backend bug -> try next
                log.exception("capture backend %s failed to open", name)
                last_exc = exc
                continue
            self._install(cap, name, index if auto else 0, mon, warning)
            return True
        code = getattr(last_exc, "code", "capture_error")
        self._fail(last_exc or CaptureError("no backend"), code)
        return False

    def _install(self, cap: CaptureBackend, name: str, index: int, mon: MonitorInfo, warning: str = "") -> None:
        self._capture = cap
        self._monitor = mon
        self._opened_index = index
        self._opened_at = self._clock()
        self._errors = 0
        with self._lock:
            st = self._stats
            st.backend, st.monitor, st.hdr_enabled = getattr(cap, "name", name), mon.label, mon.hdr_enabled
            st.state, st.last_error, st.error_code = "running", "", ""
            st.warning = warning or ("hdr" if mon.hdr_enabled else "")
        log.info("Capture opened: backend=%s monitor=%s hdr=%s", name, mon.label, mon.hdr_enabled)

    def _try_promote(self) -> None:
        """Running on a fallback backend in auto mode: periodically try to get
        back to the preferred (faster) one without a capture gap."""
        self._opened_at = self._clock()  # rate-limits attempts
        mon = self._monitor
        if mon is None:
            return
        for index, name in enumerate(AUTO_ORDER[: self._opened_index]):
            try:
                cap = self._backend_factory(name)
                cap.open(mon, self.config.region)
            except Exception as exc:
                log.debug("promotion to %s failed: %s", name, exc)
                continue
            self._close_capture()
            log.info("Capture promoted back to preferred backend %s", name)
            self._install(cap, name, index, mon)
            return

    def _tick(self) -> float:
        cfg = self.config
        tick = 1.0 / max(1.0, max(cfg.analysis_fps, cfg.output_hz))
        with self._lock:
            paused, reopen = self._paused, self._reopen
            self._reopen = False
        if paused:
            self._close_capture()
            with self._lock:
                self._stats.state = "paused"
            return 0.25
        if reopen:
            self._close_capture()
        if self._capture is None:
            now = self._clock()
            if now < self._next_retry:
                return min(0.5, self._next_retry - now)
            if not self._open_capture():
                return 0.1
        elif cfg.backend == "auto" and self._opened_index > 0 and self._clock() - self._opened_at >= self.PROMOTE_AFTER_S:
            self._try_promote()

        t0 = self._clock()
        # Only touch the capture API when an analysis is due: a full-resolution
        # readback costs several ms, transitions alone do not need new frames.
        due = t0 - self._last_analysis >= 1.0 / max(1.0, cfg.analysis_fps) - 0.002
        try:
            frame = self._capture.grab() if (self._capture and due) else None
        except CaptureError as exc:
            self._fail(exc, getattr(exc, "code", "capture_error"))
            return 0.1
        except Exception as exc:  # pragma: no cover
            self._fail(exc, "capture_error")
            return 0.1
        t1 = self._clock()
        now = t1
        st = self._stats

        if frame is not None:
            self._capture_meter.tick()
            self._last_new_frame = now
            with self._lock:
                st.frames_captured += 1
                st.capture_ms = _ema(st.capture_ms, (t1 - t0) * 1000)
            self._last_analysis = now
            self._analyze(frame.rgb, now)
        elif due:
            # DXGI returns no frame when nothing changed on screen
            self._last_analysis = now
            with self._lock:
                st.frames_no_change += 1

        t2 = self._clock()
        cur = self._transition.step(t2)
        if cur is not None:
            out = cfg.output
            if cfg.hdr_compensation and st.hdr_enabled:
                out = replace(out, saturation=int(out.saturation * HDR_SATURATION_BOOST))
            colors = finalize(cur, out)
            sent = self._deadband.filter(colors, self._transition.converged())
            with self._lock:
                st.output = colors
                st.deadband_suppressed = self._deadband.suppressed
            if sent is not None:
                try:
                    self._sink(sent)
                    with self._lock:
                        st.submissions += 1
                except Exception:  # pragma: no cover
                    log.exception("colour sink failed")
        t3 = self._clock()
        with self._lock:
            st.transition_ms = _ema(st.transition_ms, (t3 - t2) * 1000)
            st.capture_fps = self._capture_meter.rate()
            st.analysis_fps = self._analysis_meter.rate()
            st.scene_cuts = self._transition.cuts
            st.swaps_prevented = self._transition.swaps_prevented
            if frame is not None:
                st.pipeline_ms = _ema(st.pipeline_ms, (t3 - t0) * 1000)
        elapsed = t3 - t0
        if elapsed > tick:
            with self._lock:
                st.frames_dropped += 1
        # idle: nothing changes on screen and the fade is done -> poll slower
        if self._transition.converged() and now - self._last_new_frame > 1.0:
            tick = max(tick, 1.0 / max(1.0, min(cfg.analysis_fps, 10.0)))
        # wake up exactly when the next analysis is due (keeps analysis_fps
        # accurate instead of quantising it to multiples of the output tick)
        next_analysis = self._last_analysis + 1.0 / max(1.0, cfg.analysis_fps) - self._clock()
        return max(0.0, min(tick - elapsed, next_analysis))

    def _analyze(self, rgb: np.ndarray, now: float) -> None:
        cfg = self.config
        t0 = self._clock()
        crop = self._letterbox.update(rgb) if cfg.analysis.ignore_letterbox else (0, 0, 0, 0)
        feats = compute_features(rgb, crop)
        cut = self._cuts.update(signature(feats.rgb), now)
        st = self._stats
        always_frames = getattr(self._capture, "name", "") in ("gdi", "synthetic")
        if always_frames and self._cuts.is_static() and self._transition.target is not None:
            with self._lock:
                st.frames_static += 1
                self._preview = rgb
            return
        # black / protected content hint
        if int(rgb.max()) <= 3:
            if self._black_since is None:
                self._black_since = now
        else:
            self._black_since = None
        result = self._analyzer.analyze(feats, scene_cut=cut)
        self._transition.set_targets(result.zones, now, result.reorderable, cut)
        self._analysis_meter.tick()
        t1 = self._clock()
        targets = finalize(self._transition.target, cfg.output) if self._transition.target is not None else None
        with self._lock:
            st.frames_analyzed += 1
            st.analysis_ms = _ema(st.analysis_ms, (t1 - t0) * 1000)
            st.mode_label = result.stats.label or result.mode.value
            st.crop = crop
            st.targets = targets
            st.palette = tuple((oklab_to_rgb(c.lab), round(c.weight, 3)) for c in result.palette[:6])
            self._preview = rgb
            black = self._black_since is not None and now - self._black_since >= BLACK_FRAME_WARN_S
            if black:
                st.warning = "black_frames"
            elif st.warning == "black_frames":
                st.warning = "hdr" if st.hdr_enabled else ""
