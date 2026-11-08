"""Profile model with strict validation (JSON <-> dataclasses)."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..color.settings import AnalysisSettings, OutputSettings, TransitionSettings
from ..effects import EffectConfig
from ..rgb import RGB, from_hex, to_hex

SCHEMA_VERSION = 1
MAX_NAME = 60
PERFORMANCE_PROFILES = ("eco", "balanced", "responsive")


class ProfileError(ValueError):
    pass


class LightMode(str, Enum):
    STATIC = "static"
    EFFECT = "effect"
    SCREEN_SYNC = "screen_sync"
    OFF = "off"


@dataclass
class StaticState:
    zone_colors: list[RGB] = field(default_factory=lambda: [(255, 0, 40)] * 4)
    zone_brightness: list[int] = field(default_factory=lambda: [100] * 4)

    def to_dict(self) -> dict[str, Any]:
        return {"zone_colors": [to_hex(c) for c in self.zone_colors], "zone_brightness": list(self.zone_brightness)}

    @classmethod
    def from_dict(cls, d: Any) -> "StaticState":
        if not isinstance(d, dict):
            raise ProfileError("static must be an object")
        cols = d.get("zone_colors", [])
        if not isinstance(cols, list) or len(cols) != 4:
            raise ProfileError("static.zone_colors must contain 4 colours")
        try:
            colors = [from_hex(c) for c in cols]
        except (ValueError, AttributeError, TypeError) as exc:
            raise ProfileError(f"invalid zone colour: {exc}") from exc
        br = d.get("zone_brightness", [100] * 4)
        if not isinstance(br, list) or len(br) != 4:
            raise ProfileError("static.zone_brightness must contain 4 values")
        try:
            bright = [int(min(max(int(b), 0), 100)) for b in br]
        except (TypeError, ValueError) as exc:
            raise ProfileError("invalid zone brightness") from exc
        return cls(colors, bright)


@dataclass
class SyncProfile:
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    transition: TransitionSettings = field(default_factory=TransitionSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    performance: str = "balanced"

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis.to_dict(),
            "transition": self.transition.to_dict(),
            "output": self.output.to_dict(),
            "performance": self.performance,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SyncProfile":
        if not isinstance(d, dict):
            raise ProfileError("screen_sync must be an object")
        perf = d.get("performance", "balanced")
        sp = cls(
            AnalysisSettings.from_dict(d.get("analysis", {})),
            TransitionSettings.from_dict(d.get("transition", {})),
            OutputSettings.from_dict(d.get("output", {})),
            perf if perf in PERFORMANCE_PROFILES else "balanced",
        )
        _clamp_sync(sp)
        return sp


def _clamp_sync(sp: SyncProfile) -> None:
    a, t, o = sp.analysis, sp.transition, sp.output
    a.black_level = min(max(a.black_level, 0.0), 0.5)
    a.subtitle_band = min(max(a.subtitle_band, 0.0), 0.4)
    a.min_cluster_share = min(max(a.min_cluster_share, 0.001), 0.2)
    a.min_palette_distance = min(max(a.min_palette_distance, 0.02), 0.3)
    a.neighbor_blend = min(max(a.neighbor_blend, 0.0), 0.3)
    for name in ("transition_speed", "smoothing", "sensitivity"):
        setattr(t, name, int(min(max(getattr(t, name), 0), 100)))
    t.min_color_difference = int(min(max(t.min_color_difference, 0), 20))
    o.brightness = int(min(max(o.brightness, 0), 100))
    o.saturation = int(min(max(o.saturation, 0), 200))
    o.min_brightness = int(min(max(o.min_brightness, 0), 40))
    o.led_gamma = float(min(max(o.led_gamma, 0.5), 3.0))
    o.led_gain = tuple(float(min(max(g, 0.0), 1.0)) for g in (list(o.led_gain) + [1.0, 1.0, 1.0])[:3])  # type: ignore[assignment]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass
class Profile:
    id: str
    name: str
    mode: LightMode = LightMode.STATIC
    master_brightness: int = 100
    static: StaticState = field(default_factory=StaticState)
    effect: EffectConfig = field(default_factory=EffectConfig)
    sync: SyncProfile = field(default_factory=SyncProfile)
    builtin: bool = False
    description: str = ""
    modified: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "mode": self.mode.value,
            "master_brightness": self.master_brightness,
            "static": self.static.to_dict(),
            "effect": self.effect.to_dict(),
            "screen_sync": self.sync.to_dict(),
            "builtin": self.builtin,
            "description": self.description,
            "modified": self.modified,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "Profile":
        if not isinstance(d, dict):
            raise ProfileError("profile must be a JSON object")
        schema = d.get("schema", SCHEMA_VERSION)
        if not isinstance(schema, int) or schema > SCHEMA_VERSION:
            raise ProfileError(f"unsupported profile schema {schema!r}")
        pid = d.get("id") or new_id()
        if not isinstance(pid, str) or not _ID_RE.match(pid):
            raise ProfileError(f"invalid profile id {pid!r}")
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProfileError("profile name is required")
        try:
            mode = LightMode(d.get("mode", "static"))
        except ValueError as exc:
            raise ProfileError(f"unknown mode {d.get('mode')!r}") from exc
        try:
            mb = int(min(max(int(d.get("master_brightness", 100)), 0), 100))
        except (TypeError, ValueError) as exc:
            raise ProfileError("invalid master_brightness") from exc
        static = StaticState.from_dict(d["static"]) if "static" in d else StaticState()
        effect = EffectConfig.from_dict(d.get("effect", {}))
        sync = SyncProfile.from_dict(d["screen_sync"]) if "screen_sync" in d else SyncProfile()
        return cls(
            id=pid,
            name=name.strip()[:MAX_NAME],
            mode=mode,
            master_brightness=mb,
            static=static,
            effect=effect,
            sync=sync,
            builtin=bool(d.get("builtin", False)),
            description=str(d.get("description", ""))[:200],
            modified=float(d.get("modified", time.time()) or time.time()),
        )

    def copy(self, **changes: Any) -> "Profile":
        p = Profile.from_dict(self.to_dict())
        for k, v in changes.items():
            setattr(p, k, v)
        return p
