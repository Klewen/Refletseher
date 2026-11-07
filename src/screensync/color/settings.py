"""Tunable parameters of the colour engine (all JSON-serialisable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum
from typing import Any


class SyncMode(str, Enum):
    DOMINANT = "dominant"
    PALETTE = "palette"
    SPATIAL = "spatial"
    CINEMATIC = "cinematic"
    ADAPTIVE = "adaptive"


class SpatialWeighting(str, Enum):
    UNIFORM = "uniform"
    CENTER = "center"
    EDGES = "edges"


@dataclass
class AnalysisSettings:
    mode: SyncMode = SyncMode.PALETTE
    black_level: float = 0.16  # OKLab L below this is "dark" (0..1)
    ignore_letterbox: bool = True
    subtitle_guard: bool = True
    subtitle_band: float = 0.22  # bottom fraction treated as subtitle area
    spatial_weighting: SpatialWeighting = SpatialWeighting.UNIFORM
    min_cluster_share: float = 0.015  # clusters smaller than this are noise
    min_palette_distance: float = 0.065  # OKLab distance between palette colours
    accent_min_share: float = 0.003  # cinematic: smallest accent that survives
    neighbor_blend: float = 0.05  # spatial mode: blend with neighbouring zones

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        d["spatial_weighting"] = self.spatial_weighting.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisSettings":
        return _from_dict(cls, data)


@dataclass
class TransitionSettings:
    transition_speed: int = 55  # 0 slow .. 100 fast
    smoothing: int = 45  # 0 none .. 100 strong temporal filtering of targets
    sensitivity: int = 60  # 0 sluggish .. 100 reacts to small changes
    min_color_difference: int = 2  # in 8-bit units for HID re-submission
    scene_cut_fast: bool = True
    flash_guard: bool = True  # photosensitivity: limit rapid big changes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransitionSettings":
        return _from_dict(cls, data)


@dataclass
class OutputSettings:
    brightness: int = 100  # 0..100 (screen-sync output brightness)
    saturation: int = 115  # 0..200 % chroma scaling
    min_brightness: int = 0  # floor for non-black output, 0..40
    led_gamma: float = 1.0  # 1.0 = send sRGB values unchanged
    led_gain: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["led_gain"] = list(self.led_gain)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutputSettings":
        obj = _from_dict(cls, data)
        obj.led_gain = tuple(float(x) for x in obj.led_gain)  # type: ignore[assignment]
        return obj


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    obj = cls()
    if not isinstance(data, dict):
        return obj
    for f in fields(cls):
        if f.name not in data:
            continue
        default = getattr(obj, f.name)
        value = data[f.name]
        try:
            if isinstance(default, Enum):
                value = type(default)(value)
            elif isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            elif isinstance(default, tuple):
                value = tuple(value)
        except (TypeError, ValueError):
            continue
        setattr(obj, f.name, value)
    return obj
