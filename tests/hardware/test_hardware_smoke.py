"""Opt-in smoke tests against the physical MS-1565 keyboard.

    uv run pytest tests/hardware --run-hardware

Only the allow-listed, non-persistent commands (0x01 select, 0x02 effect) are
sent. Nothing is saved to flash. The keyboard ends in a calm blue.
"""

from __future__ import annotations

import time

import pytest

from screensync.device import protocol as P
from screensync.device.driver import HardwareEffect, Ms1565Driver
from screensync.device.transport import HidapiBackend, select_device
from screensync.device.worker import DeviceWorker, WorkerConfig

pytestmark = pytest.mark.hardware

CALM = (0, 80, 255)


@pytest.fixture
def driver():
    backend = HidapiBackend()
    info = select_device(backend.enumerate())
    drv = Ms1565Driver(backend.open(info))
    yield drv
    try:
        drv.apply_zone_colors([CALM] * 4)
    finally:
        drv.close()


def test_device_enumerates_exactly_once():
    devs = [d for d in HidapiBackend().enumerate() if d.vendor_id == P.VENDOR_ID and d.product_id == P.PRODUCT_ID]
    assert len(devs) == 1
    assert devs[0].usage_page == P.EXPECTED_USAGE_PAGE and devs[0].usage == P.EXPECTED_USAGE


def test_per_zone_writes_succeed(driver):
    for z, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]):
        driver.set_steady(P.ZONE_MASKS[z], c)
    assert driver.stats.packets == 8


def test_native_effect_write_succeeds(driver):
    driver.apply_effect(HardwareEffect(P.EffectType.COLOR_WAVE, ((255, 0, 0), (0, 0, 255)), speed_cs=400))
    time.sleep(1.0)


def test_worker_rate_limit_on_hardware():
    backend = HidapiBackend()
    w = DeviceWorker(lambda: backend, WorkerConfig(update_hz=10))
    w.start()
    try:
        t0 = time.perf_counter()
        for i in range(60):
            w.submit_colors(((i * 4, 0, 255 - i * 4),) * 4)
            time.sleep(0.02)
        assert w.wait_idle(3)
        elapsed = time.perf_counter() - t0
        snap = w.snapshot()
        assert snap.error_count == 0
        assert snap.frames_applied <= elapsed * 10 + 2
        w.submit_colors((CALM,) * 4)
        assert w.wait_idle(2)
    finally:
        w.stop()
