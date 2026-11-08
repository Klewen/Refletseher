"""Small, dependency-free RGB helpers shared by every layer."""

from __future__ import annotations

import re
from typing import Iterable, Sequence

RGB = tuple[int, int, int]
ZoneColors = tuple[RGB, RGB, RGB, RGB]

BLACK: RGB = (0, 0, 0)
ZONE_COUNT = 4

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def clamp_byte(value: float) -> int:
    """Clamp and round a number into 0..255."""
    if value != value:  # NaN guard
        return 0
    return 0 if value <= 0 else 255 if value >= 255 else int(round(value))


def clamp_rgb(color: Iterable[float]) -> RGB:
    r, g, b = tuple(color)
    return clamp_byte(r), clamp_byte(g), clamp_byte(b)


def is_valid_rgb(color: object) -> bool:
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        return False
    return all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)


def to_hex(color: Sequence[int]) -> str:
    r, g, b = clamp_rgb(color)
    return f"#{r:02X}{g:02X}{b:02X}"


def from_hex(text: str) -> RGB:
    match = _HEX_RE.match(text.strip())
    if not match:
        raise ValueError(f"Invalid HEX colour: {text!r}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def scale(color: Sequence[float], factor: float) -> RGB:
    factor = max(0.0, factor)
    return clamp_rgb(c * factor for c in color)


def lerp(a: Sequence[float], b: Sequence[float], t: float) -> RGB:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return clamp_rgb(a[i] + (b[i] - a[i]) * t for i in range(3))


def uniform(color: RGB) -> ZoneColors:
    return (color, color, color, color)


def as_zone_colors(colors: Sequence[Sequence[int]]) -> ZoneColors:
    if len(colors) != ZONE_COUNT:
        raise ValueError(f"Expected {ZONE_COUNT} zone colours, got {len(colors)}")
    return tuple(clamp_rgb(c) for c in colors)  # type: ignore[return-value]


def hsv_to_rgb(h: float, s: float, v: float) -> RGB:
    """h in degrees [0, 360), s/v in [0, 1]."""
    h = (h % 360.0) / 60.0
    s = min(max(s, 0.0), 1.0)
    v = min(max(v, 0.0), 1.0)
    i = int(h) % 6
    f = h - int(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return clamp_rgb((r * 255, g * 255, b * 255))


def rgb_to_hsv(color: Sequence[int]) -> tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in color)
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == r:
        h = (60 * ((g - b) / d)) % 360
    elif mx == g:
        h = 60 * ((b - r) / d) + 120
    else:
        h = 60 * ((r - g) / d) + 240
    s = 0.0 if mx == 0 else d / mx
    return h, s, mx
