"""Capture abstractions shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

ANALYSIS_WIDTH = 160  # analysis frames are at most this wide (16:9 -> 160x90)


class CaptureError(Exception):
    code = "capture_error"


class CaptureUnavailable(CaptureError):
    """Backend cannot be used on this system (missing module, no adapter)."""

    code = "unavailable"


class CaptureAccessLost(CaptureError):
    """Desktop switched (UAC/lock screen), mode change or exclusive fullscreen."""

    code = "access_lost"


class MonitorGone(CaptureError):
    code = "monitor_gone"


@dataclass(frozen=True)
class MonitorInfo:
    id: str  # GDI device name, e.g. \\.\DISPLAY1
    index: int  # 0-based order
    name: str  # friendly monitor name
    x: int
    y: int
    width: int  # physical pixels
    height: int
    primary: bool = False
    dpi_scale: float = 1.0
    refresh_hz: float = 0.0
    hdr_supported: bool = False
    hdr_enabled: bool = False

    @property
    def label(self) -> str:
        return f"{self.index + 1}: {self.name} - {self.width}x{self.height}"


@dataclass(frozen=True)
class Region:
    """Fractional sub-rectangle of a monitor (resolution/DPI independent)."""

    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    def clamp(self) -> "Region":
        x = min(max(self.x, 0.0), 0.95)
        y = min(max(self.y, 0.0), 0.95)
        w = min(max(self.w, 0.05), 1.0 - x)
        h = min(max(self.h, 0.05), 1.0 - y)
        return Region(x, y, w, h)

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        r = self.clamp()
        left = int(round(r.x * width))
        top = int(round(r.y * height))
        right = max(left + 8, int(round((r.x + r.w) * width)))
        bottom = max(top + 8, int(round((r.y + r.h) * height)))
        return left, top, min(right, width), min(bottom, height)

    @property
    def is_full(self) -> bool:
        return self.x <= 0 and self.y <= 0 and self.w >= 1 and self.h >= 1


@dataclass
class CapturedFrame:
    rgb: np.ndarray  # small analysis frame (h, w, 3) uint8 RGB
    source_size: tuple[int, int]  # (width, height) of the captured area
    timestamp: float


@runtime_checkable
class CaptureBackend(Protocol):
    name: str

    def open(self, monitor: MonitorInfo, region: Region) -> None: ...

    def grab(self) -> CapturedFrame | None:
        """Newest frame or ``None`` when the screen has not changed."""
        ...

    def close(self) -> None: ...


def reduce_frame(frame: np.ndarray, channels_bgr: bool, target_width: int = ANALYSIS_WIDTH) -> np.ndarray:
    """Cheap high-resolution -> analysis-resolution reduction.

    Integer striding first (touches ~1/16 of the memory of a 1440p frame),
    then area interpolation for proper averaging. Returns RGB uint8."""
    h, w = frame.shape[:2]
    step = max(1, int(w // (target_width * 4)))
    view = frame[::step, ::step, :3]
    vh, vw = view.shape[:2]
    tw = min(target_width, vw)
    th = max(1, int(round(vh * tw / vw)))
    small = cv2.resize(np.ascontiguousarray(view), (tw, th), interpolation=cv2.INTER_AREA)
    if channels_bgr:
        small = small[:, :, ::-1]
    return np.ascontiguousarray(small)
