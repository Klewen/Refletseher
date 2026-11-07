"""Application settings (persisted as JSON in %APPDATA%\\ScreenSyncRGB)."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ..profiles.store import atomic_write_json

log = logging.getLogger(__name__)

LANGUAGES = ("tr", "en")
THEMES = ("dark", "light")
EXIT_ACTIONS = ("restore", "keep", "off")
BACKENDS = ("auto", "dxgi", "winrt", "gdi")
PERFORMANCE = ("eco", "balanced", "responsive")


@dataclass
class AutomationRule:
    id: str
    kind: str  # "process" | "schedule" | "fullscreen"
    profile_id: str
    enabled: bool = True
    processes: list[str] = field(default_factory=list)
    start: str = "23:00"
    end: str = "07:00"
    revert: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AutomationRule | None":
        try:
            kind = d["kind"]
            if kind not in ("process", "schedule", "fullscreen"):
                return None
            return cls(
                id=str(d["id"]),
                kind=kind,
                profile_id=str(d["profile_id"]),
                enabled=bool(d.get("enabled", True)),
                processes=[str(p).lower() for p in d.get("processes", []) if str(p).strip()],
                start=str(d.get("start", "23:00")),
                end=str(d.get("end", "07:00")),
                revert=bool(d.get("revert", True)),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class AppSettings:
    language: str = "tr"
    theme: str = "dark"
    start_with_windows: bool = False
    start_minimized: bool = False
    close_to_tray: bool = True
    startup_profile: str = "last"  # "last" | "none" | profile id
    exit_action: str = "restore"
    capture_backend: str = "auto"
    monitor_id: str | None = None
    region: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    performance: str = "balanced"
    update_hz: float = 10.0
    hardware_enabled: bool = True
    ack_read: bool = True
    refresh_interval_s: float = 0.0
    auto_recovery: bool = True
    hdr_compensation: bool = True
    conflict_warning: bool = True
    debug_logging: bool = False
    favorites: list[str] = field(default_factory=lambda: ["#FF0000", "#0050FF", "#00E0C0", "#B000FF", "#FFFFFF"])
    recent_profiles: list[str] = field(default_factory=list)
    last_profile_id: str | None = None
    last_manual_profile_id: str | None = None
    default_profile_id: str | None = None
    automation: list[AutomationRule] = field(default_factory=list)
    automation_enabled: bool = False
    window_geometry: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Any) -> "AppSettings":
        s = cls()
        if not isinstance(data, dict):
            return s
        for f in fields(cls):
            if f.name not in data:
                continue
            v = data[f.name]
            try:
                if f.name == "automation":
                    rules = [AutomationRule.from_dict(r) for r in v if isinstance(r, dict)]
                    setattr(s, f.name, [r for r in rules if r is not None])
                    continue
                default = getattr(s, f.name)
                if isinstance(default, bool):
                    v = bool(v)
                elif isinstance(default, float):
                    v = float(v)
                elif isinstance(default, int):
                    v = int(v)
                elif isinstance(default, list):
                    v = list(v)
                elif default is None and v is not None:
                    v = str(v)
                setattr(s, f.name, v)
            except (TypeError, ValueError):
                log.warning("invalid setting %s=%r ignored", f.name, v)
        s.validate()
        return s

    def validate(self) -> None:
        if self.language not in LANGUAGES:
            self.language = "tr"
        if self.theme not in THEMES:
            self.theme = "dark"
        if self.exit_action not in EXIT_ACTIONS:
            self.exit_action = "restore"
        if self.capture_backend not in BACKENDS:
            self.capture_backend = "auto"
        if self.performance not in PERFORMANCE:
            self.performance = "balanced"
        self.update_hz = float(min(max(self.update_hz, 1.0), 15.0))
        self.refresh_interval_s = float(min(max(self.refresh_interval_s, 0.0), 600.0))
        if len(self.region) != 4:
            self.region = [0.0, 0.0, 1.0, 1.0]
        self.region = [float(min(max(v, 0.0), 1.0)) for v in self.region]
        self.recent_profiles = [str(p) for p in self.recent_profiles][:6]
        self.favorites = [str(c) for c in self.favorites][:16]


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.settings = self.load()

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            return AppSettings.from_dict(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError) as exc:
            log.error("settings unreadable (%s) - using defaults", exc)
            return AppSettings()

    def save(self) -> None:
        with self._lock:
            self.settings.validate()
            atomic_write_json(self.path, self.settings.to_dict())

    def update(self, **changes: Any) -> AppSettings:
        with self._lock:
            for k, v in changes.items():
                if not hasattr(self.settings, k):
                    raise AttributeError(k)
                setattr(self.settings, k, v)
            self.save()
            return self.settings


# Performance profiles. The HID cap (<= 15 Hz, token bucket) applies to all.
PERFORMANCE_PRESETS: dict[str, dict[str, float]] = {
    "eco": {"analysis_fps": 6.0, "output_hz": 20.0, "update_hz": 6.0},
    "balanced": {"analysis_fps": 12.0, "output_hz": 30.0, "update_hz": 10.0},
    "responsive": {"analysis_fps": 24.0, "output_hz": 30.0, "update_hz": 15.0},
}
