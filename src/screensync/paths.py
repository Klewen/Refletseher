"""Where ScreenSync RGB keeps its local data (never in the install folder)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ScreenSyncRGB"


def data_dir() -> Path:
    override = os.environ.get("SCREENSYNC_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:  # pragma: no cover
        base = Path.home() / ".config" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_dir() -> Path:
    override = os.environ.get("SCREENSYNC_HOME")
    if override:
        p = Path(override) / "logs"
    elif sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME / "logs"
    else:  # pragma: no cover
        p = Path.home() / ".cache" / APP_NAME / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    return data_dir() / "settings.json"


def profiles_file() -> Path:
    return data_dir() / "profiles.json"


def resource_path(*parts: str) -> Path:
    """Bundled read-only resources (works from source and PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidate = base.joinpath(*parts)
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent.joinpath(*parts)
