"""Tiny JSON based localisation. Turkish is the primary language.

    from screensync.i18n import tr
    tr("dashboard.title")
    tr("sync.fps", fps=12.5)

Missing keys fall back to English, then to the key itself (and are logged
once), so a missing translation never crashes the UI.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
SUPPORTED = {"tr": "Türkçe", "en": "English"}
_current = "tr"
_missing: set[str] = set()


@lru_cache(maxsize=None)
def load_locale(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        log.error("locale %s could not be loaded", lang)
        return {}
    return {str(k): str(v) for k, v in data.items()}


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in SUPPORTED else "tr"


def language() -> str:
    return _current


def tr(key: str, **fmt: object) -> str:
    text = load_locale(_current).get(key)
    if text is None:
        text = load_locale("en").get(key)
        if key not in _missing:
            _missing.add(key)
            log.warning("missing translation: %s", key)
        if text is None:
            text = key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, ValueError, IndexError):
            return text
    return text
