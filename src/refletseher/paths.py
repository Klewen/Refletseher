"""Where Refletseher keeps its local data (never in the install folder)."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Refletseher"
#: data folder used before the app was renamed (v1.0.x "ScreenSync RGB")
LEGACY_APP_NAMES = ("ScreenSync" + "RGB",)

log = logging.getLogger(__name__)


def migrate_legacy_data(new: Path, parent: Path) -> bool:
    """First run after the rename: copy settings/profiles from the old data
    folder so nothing is lost. The old folder is left untouched."""
    if new.exists():
        return False
    for legacy in LEGACY_APP_NAMES:
        old = parent / legacy
        if old.is_dir() and any(old.glob("*.json")):
            new.mkdir(parents=True, exist_ok=True)
            for f in old.glob("*.json"):
                shutil.copy2(f, new / f.name)
            log.info("Migrated settings and profiles from %s", old)
            return True
    return False


def data_dir() -> Path:
    override = os.environ.get("REFLETSEHER_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        parent = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        base = parent / APP_NAME
        migrate_legacy_data(base, parent)
    else:  # pragma: no cover
        base = Path.home() / ".config" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_dir() -> Path:
    override = os.environ.get("REFLETSEHER_HOME")
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
