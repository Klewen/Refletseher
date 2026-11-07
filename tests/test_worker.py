from __future__ import annotations

import threading
import time

import pytest

from screensync.device import protocol as P
from screensync.device.driver import HardwareEffect
from screensync.device.mock import MockBackend
from screensync.device.ratelimit import MinInterval, RateMeter, TokenBucket, backoff_delay
from screensync.device.worker import ConnectionState, DeviceWorker, WorkerConfig

RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def make_worker(backend: MockBackend, **cfg) -> DeviceWorker:
    cfg.setdefault("update_hz", 15.0)
    cfg.setdefault("backoff_base_s", 0.05)
    cfg.setdefault("backoff_cap_s", 0.2)
    w = DeviceWorker(lambda: backend, WorkerConfig(**cfg))
    w.start()
    return w


def wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def pairs(packets):
    """Every select must be followed by an effect packet."""
    assert len(packets) % 2 == 0
    for sel, eff in zip(packets[::2], packets[1::2]):
        assert sel[1] == P.PacketId.SELECT_ZONES
        assert eff[1] == P.PacketId.SET_EFFECT
    return list(zip(packets[::2], packets[1::2]))


@pytest.fixture
def backend():
    return MockBackend()


def test_connects_and_writes_zone_colors(backend):
    w = make_worker(backend)
    try:
        assert wait_for(lambda: w.snapshot().connected)
        w.submit_colors((RED, GREEN, BLUE, WHITE))
        assert w.wait_idle()
        assert backend.zone_colors() == (RED, GREEN, BLUE, WHITE)
        pairs(backend.packets)
        snap = w.snapshot()
        assert snap.confirmed_zone_colors == (RED, GREEN, BLUE, WHITE)
        assert not snap.pending
        assert snap.last_written_at is not None
    finally:
        w.stop()


def test_duplicate_updates_suppressed(backend):
    w = make_worker(backend)
    try:
        w.submit_colors((RED,) * 4)
        assert w.wait_idle()
        n = len(backend.packets)
        assert n == 2  # grouped into one 0x0F write
        for _ in range(5):
            w.submit_colors((RED,) * 4)
            assert w.wait_idle()
        assert len(backend.packets) == n
        assert w.snapshot().duplicates_skipped >= 5
    finally:
        w.stop()


def test_only_changed_zones_written(backend):
    w = make_worker(backend)
    try:
        w.submit_colors((RED, RED, RED, RED))
        assert w.wait_idle()
        backend.clear()
        w.submit_colors((RED, BLUE, RED, RED))
        assert w.wait_idle()
        (sel, eff), = pairs(backend.packets)
        assert sel[2] == 0x02
        assert P.decode_keyframes(eff)[0].color == BLUE
    finally:
        w.stop()


def test_rate_limit_and_coalescing(backend):
    w = make_worker(backend, update_hz=5.0)
    try:
        assert wait_for(lambda: w.snapshot().connected)
        start = time.monotonic()
        for i in range(60):  # 60 submissions over ~0.6 s
            w.submit_colors(((i, 0, 0), (0, i, 0), (0, 0, i), (i, i, i)))
            time.sleep(0.01)
        assert w.wait_idle(3)
        elapsed = time.monotonic() - start
        frames = w.snapshot().frames_applied
        assert frames <= elapsed * 5 + 2
        # final state is always the latest submission
        assert backend.zone_colors() == ((59, 0, 0), (0, 59, 0), (0, 0, 59), (59, 59, 59))
        assert w.snapshot().frames_coalesced > 0
        # inter-frame spacing honours 1/update_hz (writes are in groups of 8)
        times = backend.write_times[::8]
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert all(g >= 0.2 * 0.9 for g in gaps)
    finally:
        w.stop()


def test_thread_safe_ordering(backend):
    w = make_worker(backend, update_hz=15.0)
    try:
        assert wait_for(lambda: w.snapshot().connected)

        def producer(k):
            for i in range(40):
                w.submit_colors(((k, i, 0),) * 4, source=f"p{k}")

        threads = [threading.Thread(target=producer, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        last = ((9, 9, 9),) * 4
        w.submit_colors(last)
        assert w.wait_idle(3)
        pairs(backend.packets)
        assert len(backend.thread_ids) == 1  # all writes from the worker thread
        assert backend.zone_colors() == last
    finally:
        w.stop()


def test_hardware_effect_then_colors(backend):
    w = make_worker(backend)
    try:
        eff = HardwareEffect(P.EffectType.BREATH, (RED, BLUE), speed_cs=300)
        w.submit_effect(eff)
        assert w.wait_idle()
        assert w.snapshot().confirmed_effect == eff
        assert backend.keyboard.zone_effect == [P.EffectType.BREATH] * 4
        n = len(backend.packets)
        w.submit_effect(eff)  # duplicate
        assert w.wait_idle()
        assert len(backend.packets) == n
        w.submit_colors((GREEN,) * 4)
        assert w.wait_idle()
        assert backend.keyboard.zone_effect == [P.EffectType.STEADY] * 4
        assert w.snapshot().confirmed_effect is None
    finally:
        w.stop()


def test_device_not_found_then_plugged(backend):
    backend.present = False
    w = make_worker(backend)
    try:
        assert wait_for(lambda: w.snapshot().state == ConnectionState.NOT_FOUND)
        w.submit_colors((RED,) * 4)
        backend.present = True
        assert wait_for(lambda: w.snapshot().connected, 3)
        assert w.wait_idle()
        assert backend.zone_colors() == (RED,) * 4
    finally:
        w.stop()


def test_disconnect_and_reconnect_resends_state(backend):
    w = make_worker(backend)
    try:
        w.submit_colors((RED, GREEN, BLUE, WHITE))
        assert w.wait_idle()
        backend.unplug()
        w.submit_colors((BLUE,) * 4)
        assert wait_for(lambda: w.snapshot().state != ConnectionState.CONNECTED)
        snap = w.snapshot()
        assert snap.error_count >= 1
        assert snap.confirmed_zone_colors == (None, None, None, None)
        assert snap.pending  # desired not confirmed while disconnected
        backend.replug()
        assert wait_for(lambda: w.snapshot().connected, 3)
        assert wait_for(lambda: backend.zone_colors() == (BLUE,) * 4, 3)
        assert backend.open_count >= 2
    finally:
        w.stop()


def test_access_denied_backoff(backend):
    backend.deny_access()
    w = make_worker(backend, backoff_base_s=0.2, backoff_cap_s=0.4)
    try:
        assert wait_for(lambda: w.snapshot().state == ConnectionState.ACCESS_DENIED)
        time.sleep(0.5)
        # no busy loop: only a handful of attempts in 0.5 s
        assert w.snapshot().consecutive_errors <= 4
        backend.replug()
        assert wait_for(lambda: w.snapshot().connected, 3)
    finally:
        w.stop()


def test_suspend_resume(backend):
    w = make_worker(backend)
    try:
        w.submit_colors((RED,) * 4)
        assert w.wait_idle()
        w.suspend()
        assert wait_for(lambda: w.snapshot().state == ConnectionState.SUSPENDED)
        assert backend.close_count >= 1
        w.resume()
        assert wait_for(lambda: w.snapshot().connected)
        # state is re-asserted after resume (MCU may have reset)
        assert wait_for(lambda: w.snapshot().confirmed_zone_colors == (RED,) * 4)
    finally:
        w.stop()


def test_clean_stop_closes_transport(backend):
    w = make_worker(backend)
    assert wait_for(lambda: w.snapshot().connected)
    assert w.stop()
    assert not w.alive
    assert backend.close_count >= 1
    assert w.snapshot().state == ConnectionState.STOPPED


def test_invalid_effect_rejected_in_caller():
    w = DeviceWorker(lambda: MockBackend())
    with pytest.raises(P.ProtocolViolation):
        w.submit_effect(HardwareEffect(P.EffectType.BREATH, ((1, 2, 3),), speed_cs=10))


def test_update_rate_clamped():
    w = DeviceWorker(lambda: MockBackend())
    w.set_update_rate(100)
    assert w.config.update_hz == 15.0
    w.set_update_rate(0)
    assert w.config.update_hz == 1.0


# ------------------------------------------------------------ rate limiter
class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_token_bucket():
    clk = FakeClock()
    b = TokenBucket(10, 2, clk)
    assert b.try_acquire() and b.try_acquire()
    assert not b.try_acquire()
    assert b.wait_time() == pytest.approx(0.1)
    clk.t += 0.1
    assert b.try_acquire()


def test_token_bucket_blocking():
    clk = FakeClock()
    b = TokenBucket(10, 1, clk)
    b.try_acquire()

    def fake_sleep(s):
        clk.t += s

    slept = b.acquire(1, sleep=fake_sleep)
    assert slept == pytest.approx(0.1)


def test_min_interval_and_meter():
    clk = FakeClock()
    g = MinInterval(0.5, clk)
    assert g.remaining() == 0
    g.mark()
    clk.t = 0.2
    assert g.remaining() == pytest.approx(0.3)
    m = RateMeter(1.0, clk)
    for _ in range(5):
        m.tick()
    assert m.rate() == 5
    clk.t = 5
    assert m.rate() == 0


def test_backoff_delay():
    assert [backoff_delay(i) for i in range(0, 8)] == [0, 1, 2, 4, 8, 16, 30, 30]
