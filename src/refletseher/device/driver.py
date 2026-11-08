"""Synchronous MS-1565 driver.

This is a direct, reusable port of the hardware-verified snippet:

    send(0x01, [mask])                     # select zones
    send(0x02, [0x01, 0x58, 0x02, ...])    # steady effect, two keyframes
    after each write: get_feature_report(0x01, 64), errors ignored

A driver instance must only be used from one thread (the DeviceWorker).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Sequence

from ..rgb import RGB
from . import protocol as P
from .transport import DeviceError, DeviceIOError, GuardedTransport, HidTransport

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HardwareEffect:
    """A native MCU animation (non-persistent; never saved to flash)."""

    effect: P.EffectType
    colors: tuple[RGB, ...]
    speed_cs: int = 300
    direction: P.WaveDirection = P.WaveDirection.LEFT_TO_RIGHT
    mask: int = P.ALL_ZONES_MASK
    loop: bool = True

    def keyframes(self) -> tuple[P.Keyframe, ...]:
        return P.evenly_spaced_keyframes(self.colors, loop=self.loop)

    def packets(self) -> list[bytes]:
        return [
            P.build_select_zones(self.mask),
            P.build_effect(self.effect, self.keyframes(), self.speed_cs, self.direction),
        ]


@dataclass
class WriteStats:
    packets: int = 0
    ack_ok: int = 0
    ack_failed: int = 0
    last_latency_ms: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    def record(self, ms: float) -> None:
        self.last_latency_ms = ms
        self.latencies_ms.append(ms)
        if len(self.latencies_ms) > 512:
            del self.latencies_ms[:256]


class Ms1565Driver:
    def __init__(self, transport: HidTransport, ack_read: bool = True, trace: bool = False) -> None:
        self._t = transport if isinstance(transport, GuardedTransport) else GuardedTransport(transport, trace)
        self.ack_read = ack_read
        self.stats = WriteStats()
        self.last_ack: bytes | None = None

    # -- primitive ---------------------------------------------------------------
    def send(self, packet: bytes) -> None:
        """Validate and write a single 64-byte feature report."""
        t0 = time.perf_counter()
        count = self._t.send_feature_report(packet)
        if count != P.PACKET_SIZE:
            raise DeviceIOError(f"Unexpected write result: {count} (expected {P.PACKET_SIZE})")
        if self.ack_read:
            try:
                self.last_ack = self._t.get_feature_report(P.REPORT_ID_ACK, P.PACKET_SIZE)
                self.stats.ack_ok += 1
            except (OSError, DeviceError):
                # The verified snippet ignores read failures as well.
                self.stats.ack_failed += 1
        self.stats.packets += 1
        self.stats.record((time.perf_counter() - t0) * 1000.0)

    # -- operations --------------------------------------------------------------
    def select_zones(self, mask: int) -> None:
        self.send(P.build_select_zones(mask))

    def set_steady(self, mask: int, color: RGB) -> None:
        """Select ``mask`` then apply a steady colour (the verified sequence)."""
        select = P.build_select_zones(mask)
        effect = P.build_steady(color)
        self.send(select)
        self.send(effect)

    def apply_zone_colors(self, colors: Sequence[RGB], only: Sequence[int] | None = None) -> int:
        """Write per-zone steady colours, grouping zones that share a colour.

        Returns the number of packets written."""
        zones = list(range(4)) if only is None else list(only)
        groups: dict[RGB, int] = {}
        for z in zones:
            groups[tuple(colors[z])] = groups.get(tuple(colors[z]), 0) | P.ZONE_MASKS[z]  # type: ignore[index]
        written = 0
        for color, mask in groups.items():
            self.set_steady(mask, color)
            written += 2
        return written

    def apply_effect(self, effect: HardwareEffect) -> None:
        for pkt in effect.packets():
            self.send(pkt)

    def close(self) -> None:
        self._t.close()
