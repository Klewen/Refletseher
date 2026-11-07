"""Lighting effects: native MCU animations and software-rendered effects.

Native effects (breath, colour cycle, wave) are preferred where they exist:
the MCU animates by itself and HID traffic is a single select+effect pair.
Effects the controller cannot do are rendered in software and streamed as
per-zone steady colours through the rate-limited DeviceWorker.

Photosensitivity: every effect has a minimum period of 1 s and no effect
produces hard on/off strobing; brightness modulation never goes below a
small floor abruptly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

import numpy as np

from ..color.colorspace import oklab_to_rgb, rgb_to_oklab
from ..device import protocol as P
from ..device.driver import HardwareEffect
from ..rgb import RGB, ZoneColors, clamp_rgb, from_hex, hsv_to_rgb, is_valid_rgb, scale, to_hex

MIN_PERIOD_S = 1.0
MIN_SEGMENT_S = 0.34  # per colour segment in cycling effects (<= ~3 changes/s)
RAINBOW = tuple(hsv_to_rgb(h, 1.0, 1.0) for h in (0, 60, 120, 180, 240, 300))


class EffectId(str, Enum):
    STATIC = "static"
    BREATHING = "breathing"
    COLOR_CYCLE = "color_cycle"
    RAINBOW = "rainbow"
    WAVE = "wave"
    GRADIENT_FLOW = "gradient_flow"
    COLOR_PULSE = "color_pulse"
    SMOOTH_TRANSITION = "smooth_transition"
    PALETTE_CYCLE = "palette_cycle"
    ZONE_CHASE = "zone_chase"
    CINEMATIC_AMBIENT = "cinematic_ambient"


@dataclass(frozen=True)
class EffectSpec:
    id: EffectId
    hardware: bool
    software: bool
    uses_direction: bool
    uses_colors: bool
    min_colors: int
    max_colors: int
    default_colors: tuple[RGB, ...]
    default_speed: int
    slow: bool = False  # long periods (ambient effects)


SPECS: dict[EffectId, EffectSpec] = {
    s.id: s
    for s in (
        EffectSpec(EffectId.STATIC, True, False, False, True, 1, 4, ((255, 0, 40),), 50),
        EffectSpec(EffectId.BREATHING, True, True, False, True, 1, 9, ((255, 0, 40), (0, 90, 255)), 45),
        EffectSpec(EffectId.COLOR_CYCLE, True, True, False, True, 2, 9, RAINBOW, 40),
        EffectSpec(EffectId.RAINBOW, True, True, True, False, 0, 0, RAINBOW, 45),
        EffectSpec(EffectId.WAVE, True, True, True, True, 2, 9, ((255, 0, 60), (120, 0, 255), (0, 160, 255)), 50),
        EffectSpec(EffectId.GRADIENT_FLOW, False, True, True, True, 2, 8, ((255, 60, 0), (255, 0, 120), (90, 0, 255)), 35),
        EffectSpec(EffectId.COLOR_PULSE, False, True, False, True, 1, 8, ((255, 20, 60), (0, 140, 255)), 40),
        EffectSpec(EffectId.SMOOTH_TRANSITION, False, True, False, True, 2, 8, ((255, 80, 0), (0, 200, 160), (140, 0, 255)), 30),
        EffectSpec(EffectId.PALETTE_CYCLE, True, True, False, True, 2, 9, ((255, 0, 80), (255, 140, 0), (0, 220, 120), (0, 90, 255)), 40),
        EffectSpec(EffectId.ZONE_CHASE, False, True, True, True, 2, 2, ((0, 200, 255), (20, 0, 60)), 45),
        EffectSpec(EffectId.CINEMATIC_AMBIENT, False, True, False, True, 2, 6, ((255, 140, 60), (60, 90, 200), (150, 60, 140)), 20, True),
    )
}


_CYCLING = {
    EffectId.COLOR_CYCLE,
    EffectId.PALETTE_CYCLE,
    EffectId.WAVE,
    EffectId.RAINBOW,
    EffectId.GRADIENT_FLOW,
    EffectId.CINEMATIC_AMBIENT,
}


def period_seconds(speed: int, slow: bool = False) -> float:
    """speed 0..100 -> cycle period. Normal: 12 s .. 1.5 s, slow: 40 s .. 8 s."""
    s = min(max(int(speed), 0), 100) / 100.0
    hi, lo = (40.0, 8.0) if slow else (12.0, 1.5)
    return max(MIN_PERIOD_S, hi * (lo / hi) ** s)


@dataclass
class EffectConfig:
    effect: EffectId = EffectId.BREATHING
    speed: int = 50
    brightness: int = 100
    direction: str = "ltr"  # ltr | rtl
    colors: list[RGB] = field(default_factory=list)
    prefer_hardware: bool = True

    @property
    def spec(self) -> EffectSpec:
        return SPECS[self.effect]

    def effective_colors(self) -> list[RGB]:
        sp = self.spec
        cols = [c for c in self.colors if is_valid_rgb(c)] if sp.uses_colors else []
        if not cols:
            cols = list(sp.default_colors)
        if sp.max_colors:
            cols = cols[: sp.max_colors]
        while len(cols) < max(1, sp.min_colors):
            cols.append(cols[-1])
        return cols

    def period(self) -> float:
        """Cycle period with the photosensitivity guard applied: every colour
        segment of a cycling effect lasts >= MIN_SEGMENT_S, so even a
        black/white palette cannot exceed ~1.5 luminance flashes per second."""
        base = period_seconds(self.speed, self.spec.slow)
        if self.effect in _CYCLING:
            n = len(RAINBOW) if self.effect == EffectId.RAINBOW else len(self.effective_colors())
            base = max(base, MIN_SEGMENT_S * max(1, n))
        return base

    @property
    def uses_hardware(self) -> bool:
        sp = self.spec
        return sp.hardware and (self.prefer_hardware or not sp.software)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect": self.effect.value,
            "speed": self.speed,
            "brightness": self.brightness,
            "direction": self.direction,
            "colors": [to_hex(c) for c in self.colors],
            "prefer_hardware": self.prefer_hardware,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EffectConfig":
        cfg = cls()
        if not isinstance(d, dict):
            return cfg
        try:
            cfg.effect = EffectId(d.get("effect", cfg.effect.value))
        except ValueError:
            pass
        cfg.speed = int(min(max(int(d.get("speed", cfg.speed)), 0), 100))
        cfg.brightness = int(min(max(int(d.get("brightness", cfg.brightness)), 0), 100))
        cfg.direction = "rtl" if d.get("direction") == "rtl" else "ltr"
        cols = []
        for c in d.get("colors", []) or []:
            try:
                cols.append(from_hex(c) if isinstance(c, str) else clamp_rgb(c))
            except (ValueError, TypeError):
                continue
        cfg.colors = cols
        cfg.prefer_hardware = bool(d.get("prefer_hardware", True))
        return cfg


# ----------------------------------------------------------- hardware path
def to_hardware(cfg: EffectConfig) -> HardwareEffect | None:
    """Native MCU effect for this config, or ``None`` if software is needed."""
    if not cfg.uses_hardware or cfg.effect == EffectId.STATIC:
        return None
    k = max(0, min(100, cfg.brightness)) / 100.0
    cols = [scale(c, k) for c in cfg.effective_colors()]
    period = cfg.period()
    speed_cs = int(min(max(round(period * 100), P.MIN_ANIMATED_SPEED_CS), P.MAX_ANIMATED_SPEED_CS))
    direction = P.WaveDirection.LEFT_TO_RIGHT if cfg.direction == "ltr" else P.WaveDirection.RIGHT_TO_LEFT
    if cfg.effect == EffectId.BREATHING:
        return HardwareEffect(P.EffectType.BREATH, tuple(cols), speed_cs, direction, loop=True)
    if cfg.effect in (EffectId.COLOR_CYCLE, EffectId.PALETTE_CYCLE):
        return HardwareEffect(P.EffectType.COLOR_CYCLE, tuple(cols), speed_cs, direction, loop=True)
    if cfg.effect == EffectId.RAINBOW:
        rb = tuple(scale(c, k) for c in RAINBOW)
        return HardwareEffect(P.EffectType.COLOR_WAVE, rb, speed_cs, direction, loop=True)
    if cfg.effect == EffectId.WAVE:
        return HardwareEffect(P.EffectType.COLOR_WAVE, tuple(cols), speed_cs, direction, loop=True)
    return None


# ----------------------------------------------------------- software path
def _lab_cycle(colors: Sequence[RGB], phase: float) -> RGB:
    """Perceptual interpolation around a closed loop of colours."""
    n = len(colors)
    if n == 1:
        return colors[0]
    x = (phase % 1.0) * n
    i = int(x) % n
    t = x - int(x)
    t = t * t * (3 - 2 * t)  # ease
    a, b = rgb_to_oklab(colors[i]), rgb_to_oklab(colors[(i + 1) % n])
    return oklab_to_rgb(a + (b - a) * t)


def _positions(direction: str) -> list[float]:
    pos = [0.0, 0.25, 0.5, 0.75]
    return pos if direction == "ltr" else pos[::-1]


def render(cfg: EffectConfig, t: float) -> ZoneColors:
    """Software rendering of any effect at time ``t`` (seconds).

    Also used to *simulate* native effects for the on-screen preview."""
    cols = cfg.effective_colors()
    period = cfg.period()
    phase = (t / period) % 1.0
    e = cfg.effect
    out: list[RGB]
    if e == EffectId.STATIC:
        c4 = (cols * 4)[:4] if len(cols) < 4 else cols[:4]
        out = list(c4)
    elif e == EffectId.BREATHING:
        cycle = int(t / period)
        color = cols[cycle % len(cols)]
        env = 0.06 + 0.94 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
        out = [scale(color, env)] * 4
    elif e in (EffectId.COLOR_CYCLE,):
        out = [_lab_cycle(cols, phase)] * 4
    elif e == EffectId.PALETTE_CYCLE:
        out = [_lab_cycle(cols, phase + z * 0.25) for z in range(4)]
    elif e == EffectId.RAINBOW:
        pos = _positions(cfg.direction)
        out = [hsv_to_rgb(360.0 * (phase - p), 1.0, 1.0) for p in pos]
    elif e == EffectId.WAVE:
        pos = _positions(cfg.direction)
        out = [_lab_cycle(cols, phase - p) for p in pos]
    elif e == EffectId.GRADIENT_FLOW:
        pos = _positions(cfg.direction)
        # zones sample a continuous gradient that slowly flows: half the
        # palette spans the keyboard, so neighbours stay close in colour
        out = [_lab_cycle(cols, phase - p * 0.5) for p in pos]
    elif e == EffectId.COLOR_PULSE:
        n = int(t / period)
        color = cols[n % len(cols)]
        rise = 0.25
        if phase < rise:
            x = phase / rise
            env = x * x * (3 - 2 * x)
        else:
            env = math.exp(-4.0 * (phase - rise) / (1 - rise))
        out = [scale(color, 0.12 + 0.88 * env)] * 4
    elif e == EffectId.SMOOTH_TRANSITION:
        n = len(cols)
        seg = t / period
        i = int(seg) % n
        x = seg - int(seg)
        hold = 0.4
        k = 0.0 if x < hold else (x - hold) / (1 - hold)
        k = k * k * (3 - 2 * k)
        a, b = rgb_to_oklab(cols[i]), rgb_to_oklab(cols[(i + 1) % n])
        out = [oklab_to_rgb(a + (b - a) * k)] * 4
    elif e == EffectId.ZONE_CHASE:
        hi, bg = cols[0], cols[1] if len(cols) > 1 else (0, 0, 0)
        p = phase * 4.0
        if cfg.direction == "rtl":
            p = 4.0 - p
        out = []
        for z in range(4):
            d = abs(((z + 0.5) - p + 2.0) % 4.0 - 2.0)
            k = max(0.0, 1.0 - d / 1.3)
            k = k * k * (3 - 2 * k)
            a, b = rgb_to_oklab(bg), rgb_to_oklab(hi)
            out.append(oklab_to_rgb(a + (b - a) * k))
    elif e == EffectId.CINEMATIC_AMBIENT:
        out = []
        for z in range(4):
            c = _lab_cycle(cols, phase + z * 0.11)
            breath = 0.85 + 0.15 * (0.5 + 0.5 * math.sin(2 * math.pi * (phase * 2 + z * 0.2)))
            out.append(scale(c, breath))
    else:  # pragma: no cover
        out = [cols[0]] * 4
    k = max(0, min(100, cfg.brightness)) / 100.0
    return tuple(scale(c, k) for c in out)  # type: ignore[return-value]


def _luminance(c: RGB) -> float:
    lin = [((v / 255) / 12.92) if v / 255 <= 0.04045 else (((v / 255) + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def flash_rate(cfg: EffectConfig, seconds: float = 12.0, fps: int = 60, amplitude: float = 0.1) -> float:
    """Worst-zone luminance flashes per second (WCAG-style: a flash is a pair
    of opposing relative-luminance swings of at least ``amplitude``)."""
    n = int(seconds * fps)
    series = np.array([[_luminance(c) for c in render(cfg, i / fps)] for i in range(n)])
    worst = 0.0
    for z in range(4):
        y = series[:, z]
        swings = 0
        ref = y[0]
        direction = 0
        for v in y[1:]:
            if direction >= 0 and v <= ref - amplitude:
                swings += 1
                direction, ref = -1, v
            elif direction <= 0 and v >= ref + amplitude:
                swings += 1
                direction, ref = 1, v
            elif (direction > 0 and v > ref) or (direction < 0 and v < ref):
                ref = v
        worst = max(worst, swings / 2 / seconds)
    return worst


Sink = Callable[[ZoneColors], None]
