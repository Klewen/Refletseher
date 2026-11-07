"""GDI (BitBlt) capture through ``mss`` - universal fallback.

Slower than DXGI on large/HDR displays (~100 ms for 1440p measured on the
target laptop) but works where Desktop Duplication is unavailable. Always
returns a frame, so the engine applies its own static-scene detection.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from .base import CaptureAccessLost, CaptureError, CapturedFrame, CaptureUnavailable, MonitorInfo, Region, reduce_frame


class MssBackend:
    name = "gdi"

    def __init__(self) -> None:
        try:
            import mss  # noqa: PLC0415
        except Exception as exc:  # pragma: no cover
            raise CaptureUnavailable(f"mss not available: {exc}") from exc
        self._mss_mod = mss
        self._sct: Any = None
        self._box: dict[str, int] | None = None

    def open(self, monitor: MonitorInfo, region: Region) -> None:
        self.close()
        factory = getattr(self._mss_mod, "MSS", None) or self._mss_mod.mss
        try:
            self._sct = factory()
        except Exception as exc:
            raise CaptureError(f"GDI capture could not start: {exc}") from exc
        left, top, right, bottom = region.to_pixels(monitor.width, monitor.height)
        self._box = {"left": monitor.x + left, "top": monitor.y + top, "width": right - left, "height": bottom - top}

    def grab(self) -> CapturedFrame | None:
        if self._sct is None or self._box is None:
            raise CaptureError("capture not open")
        try:
            shot = self._sct.grab(self._box)
        except Exception as exc:
            raise CaptureAccessLost(f"GDI grab failed: {exc}") from exc
        frame = np.asarray(shot)  # BGRA
        small = reduce_frame(frame, channels_bgr=True)
        return CapturedFrame(small, (self._box["width"], self._box["height"]), time.perf_counter())

    def close(self) -> None:
        sct, self._sct = self._sct, None
        if sct is not None:
            try:
                sct.close()
            except Exception:  # pragma: no cover
                pass
