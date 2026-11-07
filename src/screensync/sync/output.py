"""Final output stage: OKLab zone colours -> 8-bit values for the LEDs."""

from __future__ import annotations

import numpy as np

from ..color.colorspace import oklab_to_srgb_u8, scale_chroma
from ..color.settings import OutputSettings
from ..rgb import RGB, ZoneColors, clamp_byte


def finalize(zones_lab: np.ndarray, out: OutputSettings) -> ZoneColors:
    lab = scale_chroma(np.asarray(zones_lab, dtype=np.float32), max(0.0, out.saturation / 100.0))
    srgb = oklab_to_srgb_u8(lab).astype(np.float32)
    srgb *= max(0.0, min(1.0, out.brightness / 100.0))
    srgb *= np.asarray(out.led_gain, dtype=np.float32)[None, :]
    if out.min_brightness > 0:
        floor = out.min_brightness / 100.0 * 255.0
        peak = srgb.max(axis=1, keepdims=True)
        lift = np.where((peak > 1.0) & (peak < floor), floor / np.maximum(peak, 1e-6), 1.0)
        srgb *= lift
    if abs(out.led_gamma - 1.0) > 1e-3:
        srgb = 255.0 * np.power(np.clip(srgb / 255.0, 0, 1), out.led_gamma)
    return tuple(tuple(clamp_byte(v) for v in row) for row in srgb)  # type: ignore[return-value]


class OutputDeadband:
    """Skip re-submitting colours that differ by less than ``min_diff`` per
    channel, but always deliver the final converged value."""

    def __init__(self, min_diff: int = 2) -> None:
        self.min_diff = min_diff
        self.last: ZoneColors | None = None
        self.suppressed = 0

    def filter(self, colors: ZoneColors, converged: bool) -> ZoneColors | None:
        if self.last is None or converged:
            if colors == self.last:
                return None
            self.last = colors
            return colors
        diff = max(abs(a - b) for ca, cb in zip(colors, self.last) for a, b in zip(ca, cb))
        if diff < self.min_diff:
            self.suppressed += 1
            return None
        self.last = colors
        return colors


def scale_zone_colors(colors: ZoneColors, factors: tuple[float, float, float, float] | float) -> ZoneColors:
    if isinstance(factors, (int, float)):
        factors = (float(factors),) * 4
    out: list[RGB] = []
    for c, f in zip(colors, factors):
        f = max(0.0, min(1.0, f))
        out.append((clamp_byte(c[0] * f), clamp_byte(c[1] * f), clamp_byte(c[2] * f)))
    return tuple(out)  # type: ignore[return-value]
