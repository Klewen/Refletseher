"""MSI MysticLight MS-1565 HID protocol: constants, packet builders, validation.

Everything that ends up on the wire is produced *and* validated here.

Hardware-verified on the user's MSI Katana 15 HX B14W (Windows 11, hidapi):
  * Feature report, report id 0x02, 64 bytes.
  * Packet 0x01 "select zones" with a one-byte zone mask.
  * Packet 0x02 "set effect" with the *steady* layout below.
  * Optional read of feature report 0x01 after each write (result ignored).

Documented by the community (natanalt gist, jeremylanes/msi-rgb,
sarpowsky/msi-katana-rgb) but not part of the original verified call:
  * Effect types 0 (disable), 2 (breath), 3 (colour cycle), 4 (colour wave).
  * Speed field = seconds * 100 (u16 little endian) for animated effects.
  * Up to 10 keyframes (time 0..100, R, G, B).

Deliberately NOT supported (never serialised, rejected by validation):
  * 0xA0 save-to-flash, 0xB0 load-from-flash, 0xFF (undocumented, MCU reset?).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Iterable, Sequence

from ..rgb import RGB, is_valid_rgb

VENDOR_ID = 0x1462
PRODUCT_ID = 0x1601
EXPECTED_PRODUCT_STRING = "MysticLight MS-1565"
EXPECTED_USAGE_PAGE = 0xFF  # reported by hidapi on the user's machine as 255
EXPECTED_USAGE = 0x01
EXPECTED_INTERFACE = 0

REPORT_ID_WRITE = 0x02
REPORT_ID_ACK = 0x01
PACKET_SIZE = 64

# Fixed bytes observed in every MSI-generated effect packet (offsets 5..8 of
# the full report, i.e. payload offsets 3..6). Their meaning is unknown, so
# we always send exactly these values.
EFFECT_CONSTANT_BYTES = (0x00, 0x00, 0x0F, 0x01)

MAX_KEYFRAMES = 10
STEADY_SPEED_CS = 600  # value MSI software and the verified call use (0x0258)

# Animated effects: the MCU accepts a wide range, MSI software uses 3..12 s.
# We allow 1..60 s. 1 s is the photosensitivity floor (<= 1 Hz full cycles).
MIN_ANIMATED_SPEED_CS = 100
MAX_ANIMATED_SPEED_CS = 6000


class PacketId(IntEnum):
    SELECT_ZONES = 0x01
    SET_EFFECT = 0x02


#: Explicit allow-list. Anything else is refused before it reaches hidapi.
ALLOWED_PACKET_IDS: frozenset[int] = frozenset({PacketId.SELECT_ZONES, PacketId.SET_EFFECT})

#: Known-dangerous packet ids, kept only to produce precise error messages.
FORBIDDEN_PACKET_IDS: dict[int, str] = {
    0xA0: "save effects to flash (persistent write)",
    0xB0: "load effects from flash",
    0xFF: "undocumented, presumably MCU restart",
}


class Zone(IntFlag):
    Z1 = 0x01
    Z2 = 0x02
    Z3 = 0x04
    Z4 = 0x08
    ALL = 0x0F


ZONE_MASKS: tuple[int, int, int, int] = (0x01, 0x02, 0x04, 0x08)
ALL_ZONES_MASK = 0x0F


class EffectType(IntEnum):
    DISABLE = 0
    STEADY = 1
    BREATH = 2
    COLOR_CYCLE = 3
    COLOR_WAVE = 4


#: Effect types whose behaviour was observed on the user's real controller
#: (2026-11-07, scripts/hw_validate.py: steady per zone, breath, cycle,
#: wave left-to-right). DISABLE (0) is documented but unused by the app.
HARDWARE_VERIFIED_EFFECTS: frozenset[EffectType] = frozenset(
    {EffectType.STEADY, EffectType.BREATH, EffectType.COLOR_CYCLE, EffectType.COLOR_WAVE}
)


class WaveDirection(IntEnum):
    RIGHT_TO_LEFT = 0
    LEFT_TO_RIGHT = 1


class ProtocolViolation(ValueError):
    """Raised when a packet would violate the safety rules or the wire format."""


@dataclass(frozen=True, slots=True)
class Keyframe:
    time: int  # 0..100 (percent of the cycle)
    color: RGB

    def __post_init__(self) -> None:
        if not isinstance(self.time, int) or not 0 <= self.time <= 100:
            raise ProtocolViolation(f"Keyframe time must be 0..100, got {self.time!r}")
        if not is_valid_rgb(self.color):
            raise ProtocolViolation(f"Invalid keyframe colour {self.color!r}")

    def to_bytes(self) -> bytes:
        r, g, b = self.color
        return bytes((self.time, r, g, b))


def mask_for_zones(zone_indices: Iterable[int]) -> int:
    mask = 0
    for idx in zone_indices:
        if not 0 <= idx < 4:
            raise ProtocolViolation(f"Zone index out of range: {idx}")
        mask |= ZONE_MASKS[idx]
    return mask


def zones_in_mask(mask: int) -> list[int]:
    return [i for i, bit in enumerate(ZONE_MASKS) if mask & bit]


def validate_zone_mask(mask: int) -> int:
    if not isinstance(mask, int) or isinstance(mask, bool) or not 0x01 <= mask <= ALL_ZONES_MASK:
        raise ProtocolViolation(f"Zone mask must be 0x01..0x0F, got {mask!r}")
    return mask


def evenly_spaced_keyframes(colors: Sequence[RGB], loop: bool = False) -> tuple[Keyframe, ...]:
    """Spread colours over 0..100. With ``loop`` the first colour is repeated at
    100 so the animation wraps seamlessly (the MCU does not wrap on its own)."""
    cols = list(colors)
    if not cols:
        raise ProtocolViolation("At least one colour is required")
    if loop and (len(cols) == 1 or cols[-1] != cols[0]):
        cols.append(cols[0])
    if len(cols) == 1:
        cols = [cols[0], cols[0]]
    if len(cols) > MAX_KEYFRAMES:
        raise ProtocolViolation(f"At most {MAX_KEYFRAMES} keyframes are accepted by the MCU")
    n = len(cols)
    frames = []
    for i, c in enumerate(cols):
        t = 100 if i == n - 1 else int(round(i * 100 / (n - 1)))
        frames.append(Keyframe(t, tuple(c)))  # type: ignore[arg-type]
    return tuple(frames)


def _validate_keyframes(frames: Sequence[Keyframe]) -> None:
    if not 2 <= len(frames) <= MAX_KEYFRAMES:
        raise ProtocolViolation(f"Need 2..{MAX_KEYFRAMES} keyframes, got {len(frames)}")
    if frames[0].time != 0 or frames[-1].time != 100:
        raise ProtocolViolation("Keyframes must start at time 0 and end at time 100")
    for prev, cur in zip(frames, frames[1:]):
        if cur.time < prev.time:
            raise ProtocolViolation("Keyframe times must be non-decreasing")
    if any(f.time == 100 for f in frames[:-1]):
        raise ProtocolViolation("Only the last keyframe may use time 100")


def _frame(packet_id: int, payload: bytes) -> bytes:
    packet = bytes((REPORT_ID_WRITE, packet_id)) + payload
    if len(packet) > PACKET_SIZE:
        raise ProtocolViolation("Payload does not fit into a 64-byte report")
    return packet.ljust(PACKET_SIZE, b"\x00")


def build_select_zones(mask: int) -> bytes:
    validate_zone_mask(mask)
    packet = _frame(PacketId.SELECT_ZONES, bytes((mask,)))
    validate_packet(packet)
    return packet


def build_effect(
    effect: EffectType,
    keyframes: Sequence[Keyframe],
    speed_cs: int = STEADY_SPEED_CS,
    direction: WaveDirection = WaveDirection.RIGHT_TO_LEFT,
) -> bytes:
    effect = EffectType(effect)
    direction = WaveDirection(direction)
    _validate_speed(effect, speed_cs)
    _validate_keyframes(keyframes)
    payload = bytearray((int(effect), speed_cs & 0xFF, (speed_cs >> 8) & 0xFF))
    payload += bytes(EFFECT_CONSTANT_BYTES)
    payload.append(int(direction))
    for kf in keyframes:
        payload += kf.to_bytes()
    packet = _frame(PacketId.SET_EFFECT, bytes(payload))
    validate_packet(packet)
    return packet


def build_steady(color: RGB) -> bytes:
    """Exactly the hardware-verified layout: steady, speed 600, direction 0,
    keyframes (0, colour) and (100, colour)."""
    if not is_valid_rgb(color):
        raise ProtocolViolation(f"Invalid colour {color!r}")
    return build_effect(
        EffectType.STEADY,
        (Keyframe(0, tuple(color)), Keyframe(100, tuple(color))),  # type: ignore[arg-type]
        speed_cs=STEADY_SPEED_CS,
        direction=WaveDirection.RIGHT_TO_LEFT,
    )


def _validate_speed(effect: EffectType, speed_cs: int) -> None:
    if not isinstance(speed_cs, int) or isinstance(speed_cs, bool):
        raise ProtocolViolation(f"Speed must be an int, got {speed_cs!r}")
    if effect in (EffectType.STEADY, EffectType.DISABLE):
        if speed_cs != STEADY_SPEED_CS:
            raise ProtocolViolation("Steady/disable packets always use speed 600")
        return
    if not MIN_ANIMATED_SPEED_CS <= speed_cs <= MAX_ANIMATED_SPEED_CS:
        raise ProtocolViolation(
            f"Animated speed must be {MIN_ANIMATED_SPEED_CS}..{MAX_ANIMATED_SPEED_CS} cs, got {speed_cs}"
        )


def decode_keyframes(packet: bytes) -> list[Keyframe]:
    """Parse keyframes of a SET_EFFECT packet (ends at the time==100 frame)."""
    frames: list[Keyframe] = []
    offset = 10
    while offset + 4 <= PACKET_SIZE and len(frames) < MAX_KEYFRAMES:
        t, r, g, b = packet[offset : offset + 4]
        if t > 100:
            raise ProtocolViolation(f"Keyframe time {t} out of range")
        frames.append(Keyframe(t, (r, g, b)))
        offset += 4
        if t == 100:
            return frames
    raise ProtocolViolation("Effect packet has no terminating keyframe (time 100) within 10 keyframes")


def validate_packet(packet: bytes) -> None:
    """Final gate before the wire. Raises :class:`ProtocolViolation`."""
    if not isinstance(packet, (bytes, bytearray)):
        raise ProtocolViolation("Packet must be bytes")
    if len(packet) != PACKET_SIZE:
        raise ProtocolViolation(f"Packet must be exactly {PACKET_SIZE} bytes, got {len(packet)}")
    if packet[0] != REPORT_ID_WRITE:
        raise ProtocolViolation(f"Report id must be 0x02, got 0x{packet[0]:02X}")
    pid = packet[1]
    if pid in FORBIDDEN_PACKET_IDS:
        raise ProtocolViolation(f"Forbidden packet 0x{pid:02X}: {FORBIDDEN_PACKET_IDS[pid]}")
    if pid not in ALLOWED_PACKET_IDS:
        raise ProtocolViolation(f"Packet id 0x{pid:02X} is not on the allow-list")

    if pid == PacketId.SELECT_ZONES:
        validate_zone_mask(packet[2])
        if any(packet[3:]):
            raise ProtocolViolation("Select-zones packet must be zero padded after the mask")
        return

    # SET_EFFECT
    try:
        effect = EffectType(packet[2])
    except ValueError as exc:
        raise ProtocolViolation(f"Unknown effect type {packet[2]}") from exc
    speed = packet[3] | (packet[4] << 8)
    _validate_speed(effect, speed)
    if tuple(packet[5:9]) != EFFECT_CONSTANT_BYTES:
        raise ProtocolViolation("Effect constant bytes must be 00 00 0F 01")
    if packet[9] not in (0, 1):
        raise ProtocolViolation(f"Direction must be 0 or 1, got {packet[9]}")
    frames = decode_keyframes(packet)
    _validate_keyframes(frames)
    end = 10 + 4 * len(frames)
    if any(packet[end:]):
        raise ProtocolViolation("Effect packet must be zero padded after the keyframes")


def describe_packet(packet: bytes) -> str:
    """Human readable one-liner used in logs and the debug console."""
    pid = packet[1] if len(packet) > 1 else -1
    if pid == PacketId.SELECT_ZONES:
        return f"SELECT mask=0x{packet[2]:02X} zones={[z + 1 for z in zones_in_mask(packet[2])]}"
    if pid == PacketId.SET_EFFECT:
        try:
            frames = decode_keyframes(packet)
            kf = " ".join(f"{f.time}:#{f.color[0]:02X}{f.color[1]:02X}{f.color[2]:02X}" for f in frames)
        except ProtocolViolation:
            kf = "?"
        name = EffectType(packet[2]).name if packet[2] in EffectType._value2member_map_ else str(packet[2])
        return f"EFFECT {name} speed={packet[3] | packet[4] << 8} dir={packet[9]} [{kf}]"
    return f"UNKNOWN 0x{pid:02X}"
