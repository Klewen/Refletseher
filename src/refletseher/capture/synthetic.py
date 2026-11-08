"""Synthetic frames for tests, benchmarks and the demo mode (no screen)."""

from __future__ import annotations

import math
import time
from typing import Callable, Sequence

import numpy as np

from ..rgb import RGB
from .base import CaptureAccessLost, CapturedFrame, MonitorInfo, Region

W, H = 160, 90

FrameFn = Callable[[float], np.ndarray]


def solid(color: RGB, w: int = W, h: int = H) -> np.ndarray:
    return np.full((h, w, 3), color, dtype=np.uint8)


def vertical_bands(colors: Sequence[RGB], w: int = W, h: int = H) -> np.ndarray:
    img = np.zeros((h, w, 3), np.uint8)
    n = len(colors)
    for i, c in enumerate(colors):
        img[:, int(i * w / n) : int((i + 1) * w / n)] = c
    return img


def horizontal_bands(colors: Sequence[RGB], w: int = W, h: int = H) -> np.ndarray:
    img = np.zeros((h, w, 3), np.uint8)
    n = len(colors)
    for i, c in enumerate(colors):
        img[int(i * h / n) : int((i + 1) * h / n), :] = c
    return img


def blobs(background: RGB, spots: Sequence[tuple[RGB, float, float, float]], w: int = W, h: int = H) -> np.ndarray:
    """Background with filled circles: (colour, cx 0..1, cy 0..1, radius as fraction of h)."""
    img = solid(background, w, h)
    yy, xx = np.mgrid[0:h, 0:w]
    for color, cx, cy, r in spots:
        m = (xx - cx * w) ** 2 + (yy - cy * h) ** 2 <= (r * h) ** 2
        img[m] = color
    return img


def with_letterbox(img: np.ndarray, bar_fraction: float = 0.12) -> np.ndarray:
    out = img.copy()
    bh = int(out.shape[0] * bar_fraction)
    out[:bh] = 0
    out[out.shape[0] - bh :] = 0
    return out


def with_subtitle(img: np.ndarray, color: RGB = (255, 255, 255)) -> np.ndarray:
    """Adds a white text-like strip (thin horizontal strokes) near the bottom."""
    out = img.copy()
    h, w = out.shape[:2]
    y0 = int(h * 0.84)
    for row in range(y0, y0 + 6, 2):
        out[row, int(w * 0.25) : int(w * 0.75) : 2] = color
    return out


def moving_scene(t: float) -> np.ndarray:
    """Slowly drifting multi-colour scene used by the benchmark/demo."""
    h1 = (t * 12) % 360
    cols = []
    for i in range(4):
        hue = (h1 + i * 70) % 360
        c = _hsv(hue, 0.8, 0.85)
        cols.append(c)
    img = vertical_bands(cols)
    yy, xx = np.mgrid[0:H, 0:W]
    cx = (0.5 + 0.35 * math.sin(t * 0.7)) * W
    m = (xx - cx) ** 2 + (yy - H / 2) ** 2 <= (H * 0.18) ** 2
    img[m] = (250, 240, 220)
    return img


def _hsv(h: float, s: float, v: float) -> RGB:
    from ..rgb import hsv_to_rgb

    return hsv_to_rgb(h, s, v)


class SyntheticBackend:
    """Capture backend that renders ``frame_fn(t)``; can simulate failures."""

    name = "synthetic"

    def __init__(self, frame_fn: FrameFn | None = None, only_on_change: bool = False) -> None:
        self.frame_fn = frame_fn or moving_scene
        self.only_on_change = only_on_change
        self._t0 = time.perf_counter()
        self._last: np.ndarray | None = None
        self.opened = 0
        self.closed = 0
        self.fail_grabs = 0
        self.is_open = False

    def open(self, monitor: MonitorInfo, region: Region) -> None:
        self.opened += 1
        self.is_open = True

    def grab(self) -> CapturedFrame | None:
        if self.fail_grabs > 0:
            self.fail_grabs -= 1
            raise CaptureAccessLost("simulated access lost")
        frame = self.frame_fn(time.perf_counter() - self._t0)
        if self.only_on_change and self._last is not None and np.array_equal(frame, self._last):
            return None
        self._last = frame
        return CapturedFrame(frame, (frame.shape[1], frame.shape[0]), time.perf_counter())

    def close(self) -> None:
        self.closed += 1
        self.is_open = False


SYNTHETIC_MONITOR = MonitorInfo(id="SYNTHETIC", index=0, name="Synthetic", x=0, y=0, width=W, height=H, primary=True)
