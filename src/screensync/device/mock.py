"""Simulated MS-1565 used by tests, the benchmark and the GUI "demo" mode.

The mock decodes the packets it receives and keeps a *simulated* model of the
keyboard. It never claims to know the real LED state.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ..rgb import BLACK, RGB
from . import protocol as P
from .transport import AccessDenied, DeviceInfo, DeviceIOError, DeviceNotFound

MOCK_INFO = DeviceInfo(
    path=b"MOCK\\VID_1462&PID_1601",
    vendor_id=P.VENDOR_ID,
    product_id=P.PRODUCT_ID,
    product="MysticLight MS-1565 (simulated)",
    manufacturer="MSI",
    usage_page=P.EXPECTED_USAGE_PAGE,
    usage=P.EXPECTED_USAGE,
    interface_number=0,
)


@dataclass
class SimulatedKeyboard:
    selected_mask: int = 0
    zone_effect: list[int] = field(default_factory=lambda: [P.EffectType.STEADY] * 4)
    zone_color: list[RGB] = field(default_factory=lambda: [BLACK] * 4)


class MockTransport:
    def __init__(self, backend: "MockBackend") -> None:
        self._b = backend
        self.closed = False

    def send_feature_report(self, data: bytes) -> int:
        b = self._b
        with b.lock:
            if self.closed:
                raise DeviceIOError("transport closed")
            if b.fail_next_writes > 0:
                b.fail_next_writes -= 1
                raise DeviceIOError("simulated write failure")
            if b.disconnected:
                raise DeviceIOError("simulated disconnect")
            if b.write_latency_s:
                time.sleep(b.write_latency_s)
            packet = bytes(data)
            b.packets.append(packet)
            b.write_times.append(time.perf_counter())
            b.thread_ids.add(threading.get_ident())
            self._apply(packet)
            return b.short_write if b.short_write else len(packet)

    def _apply(self, packet: bytes) -> None:
        kb = self._b.keyboard
        if packet[1] == P.PacketId.SELECT_ZONES:
            kb.selected_mask = packet[2]
        elif packet[1] == P.PacketId.SET_EFFECT:
            frames = P.decode_keyframes(packet)
            for z in P.zones_in_mask(kb.selected_mask):
                kb.zone_effect[z] = packet[2]
                kb.zone_color[z] = frames[0].color

    def get_feature_report(self, report_id: int, length: int) -> bytes:
        with self._b.lock:
            self._b.ack_reads += 1
            if self._b.ack_raises:
                raise DeviceIOError("simulated ack failure")
            return bytes([report_id]) + bytes(length - 1)

    def close(self) -> None:
        self.closed = True
        with self._b.lock:
            self._b.close_count += 1


class MockBackend:
    name = "mock"

    def __init__(self, present: bool = True, write_latency_s: float = 0.0) -> None:
        self.lock = threading.RLock()
        self.present = present
        self.write_latency_s = write_latency_s
        self.packets: list[bytes] = []
        self.write_times: list[float] = []
        self.thread_ids: set[int] = set()
        self.keyboard = SimulatedKeyboard()
        self.open_count = 0
        self.close_count = 0
        self.ack_reads = 0
        self.ack_raises = True  # mimics Windows where the read often fails
        self.fail_next_writes = 0
        self.fail_open: Exception | None = None
        self.disconnected = False
        self.short_write = 0
        self.extra_devices: list[DeviceInfo] = []

    # -- DeviceBackend protocol -------------------------------------------------
    def enumerate(self) -> list[DeviceInfo]:
        with self.lock:
            devs = [MOCK_INFO] if self.present and not self.disconnected else []
            return devs + list(self.extra_devices)

    def open(self, info: DeviceInfo) -> MockTransport:
        with self.lock:
            if self.fail_open is not None:
                raise self.fail_open
            if not self.present or self.disconnected:
                raise DeviceNotFound("simulated: device not present")
            self.open_count += 1
            return MockTransport(self)

    # -- helpers for tests -----------------------------------------------------
    def deny_access(self) -> None:
        self.fail_open = AccessDenied("simulated access denied")

    def unplug(self) -> None:
        with self.lock:
            self.disconnected = True

    def replug(self) -> None:
        with self.lock:
            self.disconnected = False
            self.fail_open = None

    def clear(self) -> None:
        with self.lock:
            self.packets.clear()
            self.write_times.clear()

    def zone_colors(self) -> tuple[RGB, RGB, RGB, RGB]:
        with self.lock:
            return tuple(self.keyboard.zone_color)  # type: ignore[return-value]
