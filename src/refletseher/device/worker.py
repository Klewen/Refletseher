"""DeviceWorker: the single thread that owns the HID connection.

All writes to the controller are serialised here. Producers (screen sync,
software effects, the GUI) only *submit a desired state*; the worker
reconciles it with what it last wrote successfully and sends the minimum set
of packets, at a bounded rate:

* latest-wins coalescing (a slow device never builds a backlog),
* exact duplicate suppression per zone,
* ``update_hz`` cap for colour frames and a hard packets/second token bucket,
* reconnect with exponential backoff, no busy retry loops,
* suspend/resume for sleep and session lock.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional, Union

from ..rgb import RGB, ZoneColors, as_zone_colors
from . import protocol as P
from .driver import HardwareEffect, Ms1565Driver
from .ratelimit import MinInterval, RateMeter, TokenBucket, backoff_delay
from .transport import (
    AccessDenied,
    AmbiguousDevice,
    DeviceBackend,
    DeviceError,
    DeviceInfo,
    DeviceNotFound,
    select_device,
)

log = logging.getLogger(__name__)

DesiredState = Union[ZoneColors, HardwareEffect]

# Measured on the user's controller: see docs/HARDWARE_VALIDATION.md.
DEFAULT_UPDATE_HZ = 10.0
MAX_UPDATE_HZ = 15.0
MIN_UPDATE_HZ = 1.0
DEFAULT_MAX_PACKETS_PER_SEC = 120.0
STALL_THRESHOLD_S = 1.5


class ConnectionState(str, Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    ERROR = "error"
    SUSPENDED = "suspended"


@dataclass
class WorkerConfig:
    update_hz: float = DEFAULT_UPDATE_HZ
    max_packets_per_sec: float = DEFAULT_MAX_PACKETS_PER_SEC
    ack_read: bool = True
    trace_packets: bool = False
    refresh_interval_s: float = 0.0  # >0: periodically re-assert the state
    backoff_base_s: float = 1.0
    backoff_cap_s: float = 30.0


@dataclass(frozen=True)
class DeviceSnapshot:
    state: ConnectionState
    backend: str
    device: Optional[DeviceInfo]
    desired: Optional[DesiredState]
    desired_source: str
    confirmed_zone_colors: tuple[Optional[RGB], Optional[RGB], Optional[RGB], Optional[RGB]]
    confirmed_effect: Optional[HardwareEffect]
    last_written_at: Optional[float]  # wall clock (time.time) of last successful write
    packets_sent: int
    frames_applied: int
    duplicates_skipped: int
    frames_coalesced: int
    rejected_packets: int
    error_count: int
    consecutive_errors: int
    last_error: str
    last_error_code: str
    retry_in_s: float
    write_latency_ms: float
    frame_latency_ms: float
    updates_per_sec: float
    packets_per_sec: float
    stalled: bool
    update_hz: float
    ack_failures: int

    @property
    def connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    @property
    def pending(self) -> bool:
        """True when the desired state is not (yet) confirmed on the device."""
        if self.desired is None:
            return False
        if isinstance(self.desired, HardwareEffect):
            return self.confirmed_effect != self.desired
        return tuple(self.confirmed_zone_colors) != tuple(self.desired)


@dataclass
class _Shared:
    desired: Optional[DesiredState] = None
    desired_seq: int = 0
    desired_source: str = ""
    submitted_at: float = 0.0
    applied_seq: int = 0
    submits_since_apply: int = 0
    reconnect_requested: bool = False
    suspended: bool = False
    stop: bool = False
    invalidate: bool = False


@dataclass
class _Stats:
    packets_sent: int = 0
    frames_applied: int = 0
    duplicates_skipped: int = 0
    frames_coalesced: int = 0
    rejected_packets: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    last_error: str = ""
    last_error_code: str = ""
    last_written_at: Optional[float] = None
    write_latency_ms: float = 0.0
    frame_latency_ms: float = 0.0
    ack_failures: int = 0
    frame_latencies: list[float] = field(default_factory=list)


class DeviceWorker:
    def __init__(
        self,
        backend_factory: Callable[[], DeviceBackend],
        config: WorkerConfig | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._backend_factory = backend_factory
        self.config = config or WorkerConfig()
        self._clock = clock
        self._cond = threading.Condition(threading.RLock())
        self._sh = _Shared()
        self._stats = _Stats()
        self._state = ConnectionState.STOPPED
        self._backend: DeviceBackend | None = None
        self._backend_name = "?"
        self._device: DeviceInfo | None = None
        self._driver: Ms1565Driver | None = None
        self._confirmed: list[Optional[RGB]] = [None, None, None, None]
        self._confirmed_effect: Optional[HardwareEffect] = None
        self._next_retry = 0.0
        self._write_started: Optional[float] = None
        self._frame_gate = MinInterval(1.0 / self._clamp_hz(self.config.update_hz), clock)
        self._bucket = TokenBucket(self.config.max_packets_per_sec, 16, clock)
        self._updates_meter = RateMeter(2.0, clock)
        self._packets_meter = RateMeter(2.0, clock)
        self._last_refresh = clock()
        self._thread: threading.Thread | None = None
        self._listeners: list[Callable[[ConnectionState, str], None]] = []

    # ------------------------------------------------------------------ public
    @staticmethod
    def _clamp_hz(hz: float) -> float:
        return min(MAX_UPDATE_HZ, max(MIN_UPDATE_HZ, float(hz)))

    def add_listener(self, fn: Callable[[ConnectionState, str], None]) -> None:
        self._listeners.append(fn)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        with self._cond:
            self._sh.stop = False
            self._set_state(ConnectionState.CONNECTING, "starting")
        self._thread = threading.Thread(target=self._run, name="DeviceWorker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> bool:
        with self._cond:
            self._sh.stop = True
            self._cond.notify_all()
        t = self._thread
        if t is not None:
            t.join(timeout)
            alive = t.is_alive()
        else:
            alive = False
        if not alive:
            self._close_device()
            self._set_state(ConnectionState.STOPPED, "stopped")
        return not alive

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def submit_colors(self, colors: ZoneColors, source: str = "") -> None:
        self._submit(as_zone_colors(colors), source)

    def submit_effect(self, effect: HardwareEffect, source: str = "") -> None:
        # Fail fast in the caller's thread on invalid effects.
        effect.packets()
        self._submit(effect, source)

    def _submit(self, state: DesiredState, source: str) -> None:
        with self._cond:
            if self._sh.desired_seq != self._sh.applied_seq:
                self._sh.submits_since_apply += 1
            self._sh.desired = state
            self._sh.desired_seq += 1
            self._sh.desired_source = source
            self._sh.submitted_at = self._clock()
            self._cond.notify_all()

    def set_update_rate(self, hz: float) -> None:
        with self._cond:
            self.config.update_hz = self._clamp_hz(hz)
            self._frame_gate.interval = 1.0 / self.config.update_hz
            self._cond.notify_all()

    def request_reconnect(self) -> None:
        with self._cond:
            self._sh.reconnect_requested = True
            self._next_retry = 0.0
            self._cond.notify_all()

    def invalidate(self) -> None:
        """Forget what the device is believed to show; the next cycle resends."""
        with self._cond:
            self._sh.invalidate = True
            self._cond.notify_all()

    def suspend(self) -> None:
        with self._cond:
            self._sh.suspended = True
            self._cond.notify_all()

    def resume(self) -> None:
        with self._cond:
            self._sh.suspended = False
            self._sh.invalidate = True
            self._sh.reconnect_requested = True
            self._next_retry = 0.0
            self._cond.notify_all()

    def wait_idle(self, timeout: float = 2.0) -> bool:
        """Block until the latest desired state has been processed (tests)."""
        end = time.perf_counter() + timeout
        with self._cond:
            while self._sh.applied_seq != self._sh.desired_seq:
                left = end - time.perf_counter()
                if left <= 0:
                    return False
                self._cond.wait(min(left, 0.05))
        return True

    def snapshot(self) -> DeviceSnapshot:
        with self._cond:
            st = self._stats
            now = self._clock()
            stalled = self._write_started is not None and now - self._write_started > STALL_THRESHOLD_S
            retry = max(0.0, self._next_retry - now) if self._state not in (
                ConnectionState.CONNECTED,
                ConnectionState.STOPPED,
            ) else 0.0
            return DeviceSnapshot(
                state=self._state,
                backend=self._backend_name,
                device=self._device,
                desired=self._sh.desired,
                desired_source=self._sh.desired_source,
                confirmed_zone_colors=tuple(self._confirmed),  # type: ignore[arg-type]
                confirmed_effect=self._confirmed_effect,
                last_written_at=st.last_written_at,
                packets_sent=st.packets_sent,
                frames_applied=st.frames_applied,
                duplicates_skipped=st.duplicates_skipped,
                frames_coalesced=st.frames_coalesced,
                rejected_packets=st.rejected_packets,
                error_count=st.error_count,
                consecutive_errors=st.consecutive_errors,
                last_error=st.last_error,
                last_error_code=st.last_error_code,
                retry_in_s=retry,
                write_latency_ms=st.write_latency_ms,
                frame_latency_ms=st.frame_latency_ms,
                updates_per_sec=self._updates_meter.rate(),
                packets_per_sec=self._packets_meter.rate(),
                stalled=stalled,
                update_hz=self.config.update_hz,
                ack_failures=st.ack_failures,
            )

    # ----------------------------------------------------------------- thread
    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        changed = state != self._state
        self._state = state
        if changed:
            log.info("Device state -> %s (%s)", state.value, detail)
            for fn in list(self._listeners):
                try:
                    fn(state, detail)
                except Exception:  # pragma: no cover
                    log.exception("device listener failed")

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:  # pragma: no cover - defensive: never crash the app
            log.exception("DeviceWorker crashed")
            with self._cond:
                self._stats.last_error = "worker crashed (see log)"
                self._stats.last_error_code = "crash"
                self._set_state(ConnectionState.ERROR, "crash")
        finally:
            self._close_device()

    def _loop(self) -> None:
        while True:
            with self._cond:
                if self._sh.stop:
                    return
                if self._sh.suspended:
                    if self._driver is not None:
                        self._close_device()
                    self._set_state(ConnectionState.SUSPENDED, "suspended")
                    self._cond.wait(0.5)
                    continue
                if self._sh.reconnect_requested:
                    self._sh.reconnect_requested = False
                    if self._driver is not None:
                        self._close_device()
                if self._sh.invalidate:
                    self._sh.invalidate = False
                    self._forget_confirmed()
                connected = self._driver is not None

            if not connected:
                now = self._clock()
                if now < self._next_retry:
                    with self._cond:
                        self._cond.wait(min(0.5, self._next_retry - now))
                    continue
                self._try_connect()
                continue

            # refresh (re-assert) timer
            if self.config.refresh_interval_s > 0 and self._clock() - self._last_refresh >= self.config.refresh_interval_s:
                self._last_refresh = self._clock()
                with self._cond:
                    self._forget_confirmed()
                    if self._sh.desired is not None and self._sh.applied_seq == self._sh.desired_seq:
                        self._sh.applied_seq -= 1  # force a pass

            with self._cond:
                if self._sh.stop:
                    return
                if self._sh.applied_seq == self._sh.desired_seq or self._sh.desired is None:
                    self._cond.wait(0.25)
                    continue
                wait = 0.0
                if not isinstance(self._sh.desired, HardwareEffect):
                    wait = self._frame_gate.remaining()
                if wait > 0:
                    # Wait for the rate gate; newer submissions coalesce meanwhile.
                    # Condition.wait is ~15.6 ms coarse on Windows; short gate
                    # waits use the high-resolution time.sleep outside the lock.
                    if wait > 0.12:
                        self._cond.wait(wait)
                        continue
            if wait > 0:
                time.sleep(wait)
                continue
            with self._cond:
                if self._sh.stop or self._sh.desired is None or self._sh.applied_seq == self._sh.desired_seq:
                    continue
                desired = self._sh.desired
                seq = self._sh.desired_seq
                submitted_at = self._sh.submitted_at
                coalesced = self._sh.submits_since_apply
                self._sh.submits_since_apply = 0

            self._apply(desired, seq, submitted_at, coalesced)

    def _forget_confirmed(self) -> None:
        self._confirmed = [None, None, None, None]
        self._confirmed_effect = None

    def _try_connect(self) -> None:
        with self._cond:
            self._set_state(ConnectionState.CONNECTING, "connecting")
        try:
            if self._backend is None:
                self._backend = self._backend_factory()
                self._backend_name = getattr(self._backend, "name", type(self._backend).__name__)
            info = select_device(self._backend.enumerate())
            transport = self._backend.open(info)
            driver = Ms1565Driver(transport, ack_read=self.config.ack_read, trace=self.config.trace_packets)
        except AccessDenied as exc:
            self._connect_failed(ConnectionState.ACCESS_DENIED, exc)
            return
        except (DeviceNotFound, AmbiguousDevice) as exc:
            self._connect_failed(ConnectionState.NOT_FOUND, exc)
            return
        except DeviceError as exc:
            self._connect_failed(ConnectionState.ERROR, exc)
            return
        except Exception as exc:  # backend construction or unexpected error
            log.exception("Unexpected error while connecting")
            self._connect_failed(ConnectionState.ERROR, exc)
            return
        with self._cond:
            self._driver = driver
            self._device = info
            self._forget_confirmed()
            self._stats.consecutive_errors = 0
            self._frame_gate.reset()
            # Re-send the desired state on (re)connect.
            if self._sh.desired is not None:
                self._sh.applied_seq = self._sh.desired_seq - 1
            self._set_state(ConnectionState.CONNECTED, info.label)

    def _connect_failed(self, state: ConnectionState, exc: Exception) -> None:
        with self._cond:
            st = self._stats
            st.consecutive_errors += 1
            if state != ConnectionState.NOT_FOUND:
                st.error_count += 1
            st.last_error = str(exc)
            st.last_error_code = getattr(exc, "code", type(exc).__name__)
            delay = backoff_delay(st.consecutive_errors, self.config.backoff_base_s, self.config.backoff_cap_s)
            self._next_retry = self._clock() + delay
            self._set_state(state, f"{exc} (retry in {delay:.0f}s)")

    def _close_device(self) -> None:
        drv = self._driver
        self._driver = None
        if drv is not None:
            try:
                drv.close()
            except Exception:  # pragma: no cover
                log.debug("close failed", exc_info=True)
        with self._cond:
            self._forget_confirmed()

    def _send_packets(self, packets: list[bytes]) -> None:
        drv = self._driver
        assert drv is not None
        for pkt in packets:
            self._bucket.acquire(1)
            with self._cond:
                self._write_started = self._clock()
            try:
                drv.send(pkt)
            finally:
                with self._cond:
                    self._write_started = None
            with self._cond:
                self._stats.packets_sent += 1
                self._stats.write_latency_ms = drv.stats.last_latency_ms
                self._stats.ack_failures = drv.stats.ack_failed
            self._packets_meter.tick()

    def _plan(self, desired: DesiredState) -> tuple[list[bytes], Callable[[], None]]:
        """Compute the packets needed and a commit callback for confirmation."""
        if isinstance(desired, HardwareEffect):
            if self._confirmed_effect == desired:
                return [], lambda: None

            def commit_effect() -> None:
                self._confirmed_effect = desired
                for z in P.zones_in_mask(desired.mask):
                    self._confirmed[z] = None

            return desired.packets(), commit_effect

        colors = desired
        changed = [z for z in range(4) if self._confirmed[z] != colors[z]]
        if not changed:
            return [], lambda: None
        groups: dict[RGB, int] = {}
        for z in changed:
            groups[colors[z]] = groups.get(colors[z], 0) | P.ZONE_MASKS[z]
        packets: list[bytes] = []
        for color, mask in groups.items():
            packets.append(P.build_select_zones(mask))
            packets.append(P.build_steady(color))

        def commit_colors() -> None:
            for z in changed:
                self._confirmed[z] = colors[z]
            self._confirmed_effect = None

        return packets, commit_colors

    def _apply(self, desired: DesiredState, seq: int, submitted_at: float, coalesced: int) -> None:
        try:
            packets, commit = self._plan(desired)
        except P.ProtocolViolation as exc:
            log.error("Rejected invalid desired state: %s", exc)
            with self._cond:
                self._stats.rejected_packets += 1
                self._stats.last_error = f"rejected: {exc}"
                self._stats.last_error_code = "protocol"
                self._sh.applied_seq = max(self._sh.applied_seq, seq)
                self._cond.notify_all()
            return

        if not packets:
            with self._cond:
                self._stats.duplicates_skipped += 1
                self._stats.frames_coalesced += coalesced
                self._sh.applied_seq = max(self._sh.applied_seq, seq)
                self._cond.notify_all()
            return

        try:
            self._send_packets(packets)
        except P.ProtocolViolation as exc:  # pragma: no cover - guarded by _plan
            log.error("Protocol guard blocked a packet: %s", exc)
            with self._cond:
                self._stats.rejected_packets += 1
                self._sh.applied_seq = max(self._sh.applied_seq, seq)
            return
        except DeviceError as exc:
            log.warning("HID write failed: %s", exc)
            self._close_device()
            self._connect_failed(ConnectionState.ERROR, exc)
            return
        except OSError as exc:  # pragma: no cover - raw hidapi error
            log.warning("HID OS error: %s", exc)
            self._close_device()
            self._connect_failed(ConnectionState.ERROR, exc)
            return

        now = self._clock()
        with self._cond:
            commit()
            if not isinstance(desired, HardwareEffect):
                self._frame_gate.mark()
            st = self._stats
            st.frames_applied += 1
            st.frames_coalesced += coalesced
            st.consecutive_errors = 0
            st.last_written_at = time.time()
            lat = (now - submitted_at) * 1000.0
            st.frame_latency_ms = lat if st.frame_latency_ms == 0 else 0.8 * st.frame_latency_ms + 0.2 * lat
            st.frame_latencies.append(lat)
            if len(st.frame_latencies) > 512:
                del st.frame_latencies[:256]
            self._sh.applied_seq = max(self._sh.applied_seq, seq)
            self._cond.notify_all()
        self._updates_meter.tick()

    # ------------------------------------------------------------- test hooks
    def frame_latencies(self) -> list[float]:
        with self._cond:
            return list(self._stats.frame_latencies)

    def with_config(self, **kw: object) -> None:
        with self._cond:
            self.config = replace(self.config, **kw)  # type: ignore[arg-type]
