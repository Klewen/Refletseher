"""Screen capture layer.

Backend preference for ``auto``: DXGI Desktop Duplication -> Windows
Graphics Capture -> GDI (mss). See docs/ARCHITECTURE.md for the evaluation.
"""

from __future__ import annotations

import logging

from .base import (
    CaptureAccessLost,
    CaptureBackend,
    CaptureError,
    CapturedFrame,
    CaptureUnavailable,
    MonitorGone,
    MonitorInfo,
    Region,
)

log = logging.getLogger(__name__)

BACKEND_NAMES = ("auto", "dxgi", "winrt", "gdi")
AUTO_ORDER = ("dxgi", "winrt", "gdi")


def create_backend(name: str) -> CaptureBackend:
    if name == "dxgi" or name == "winrt":
        from .dxcam_backend import DxcamBackend

        return DxcamBackend(name)
    if name == "gdi":
        from .gdi_backend import MssBackend

        return MssBackend()
    raise CaptureUnavailable(f"unknown backend {name}")


def available_backends() -> list[str]:
    out = []
    for n in AUTO_ORDER:
        try:
            create_backend(n)
            out.append(n)
        except CaptureUnavailable:
            continue
    return out


__all__ = [
    "AUTO_ORDER",
    "BACKEND_NAMES",
    "CaptureAccessLost",
    "CaptureBackend",
    "CaptureError",
    "CapturedFrame",
    "CaptureUnavailable",
    "MonitorGone",
    "MonitorInfo",
    "Region",
    "available_backends",
    "create_backend",
]
