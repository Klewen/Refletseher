"""Built-in presets (seeded into the profile store, restorable)."""

from __future__ import annotations

from ..color.settings import AnalysisSettings, OutputSettings, SpatialWeighting, SyncMode, TransitionSettings
from ..effects import EffectConfig, EffectId
from .model import LightMode, Profile, StaticState, SyncProfile


def _static(pid: str, name: str, colors, brightness: int = 100, desc: str = "") -> Profile:
    cols = list(colors) if len(colors) == 4 else [colors[0]] * 4
    return Profile(pid, name, LightMode.STATIC, brightness, StaticState(cols, [100] * 4), builtin=True, description=desc)


def _effect(pid: str, name: str, cfg: EffectConfig, desc: str = "") -> Profile:
    return Profile(pid, name, LightMode.EFFECT, 100, StaticState([cfg.effective_colors()[0]] * 4), cfg, builtin=True, description=desc)


def _sync(pid: str, name: str, mode: SyncMode, speed: int, smoothing: int, saturation: int, perf: str, desc: str = "", **an) -> Profile:
    sp = SyncProfile(
        AnalysisSettings(mode=mode, **an),
        TransitionSettings(transition_speed=speed, smoothing=smoothing),
        OutputSettings(saturation=saturation),
        perf,
    )
    return Profile(pid, name, LightMode.SCREEN_SYNC, 100, StaticState(), EffectConfig(), sp, builtin=True, description=desc)


def builtin_presets() -> list[Profile]:
    return [
        _sync("preset_cinematic", "Cinematic Ambient", SyncMode.CINEMATIC, 35, 60, 120, "balanced", "preset.cinematic"),
        _sync("preset_gaming", "Gaming Dynamic", SyncMode.SPATIAL, 82, 20, 125, "responsive", "preset.gaming",
              spatial_weighting=SpatialWeighting.EDGES, ignore_letterbox=False, subtitle_guard=False),
        _static("preset_deep_blue", "Deep Blue", [(0, 40, 255)], desc="preset.deep_blue"),
        _static("preset_msi_red", "MSI Red", [(255, 0, 0)], desc="preset.msi_red"),
        _static("preset_cyberpunk", "Cyberpunk", [(255, 0, 170), (170, 0, 255), (0, 200, 255), (255, 230, 0)], desc="preset.cyberpunk"),
        _effect("preset_ocean", "Ocean",
                EffectConfig(EffectId.GRADIENT_FLOW, speed=25, colors=[(0, 40, 200), (0, 150, 220), (0, 220, 170)], prefer_hardware=False),
                "preset.ocean"),
        _static("preset_sunset", "Sunset", [(255, 60, 0), (255, 120, 20), (230, 40, 90), (140, 20, 140)], desc="preset.sunset"),
        _effect("preset_rainbow", "Rainbow", EffectConfig(EffectId.RAINBOW, speed=45, prefer_hardware=True), "preset.rainbow"),
        _static("preset_night", "Night Mode", [(255, 90, 20)], brightness=22, desc="preset.night"),
        _static("preset_white", "Minimal White", [(255, 240, 225)], brightness=70, desc="preset.white"),
        _sync("preset_adaptive", "Screen Adaptive", SyncMode.ADAPTIVE, 55, 45, 115, "balanced", "preset.adaptive"),
        _static("preset_custom", "Custom Profile", [(255, 0, 80), (200, 0, 255), (0, 120, 255), (0, 230, 200)], desc="preset.custom"),
    ]


PRESET_IDS = tuple(p.id for p in builtin_presets())
NIGHT_PRESET_ID = "preset_night"
GAMING_PRESET_ID = "preset_gaming"
