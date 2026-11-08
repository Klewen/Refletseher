"""Scene-change detection on a tiny colour signature."""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from .colorspace import srgb_u8_to_oklab


def signature(rgb: np.ndarray, grid: int = 4) -> np.ndarray:
    """(grid*grid, 3) OKLab means of a coarse grid over the frame."""
    small = cv2.resize(np.ascontiguousarray(rgb), (grid, grid), interpolation=cv2.INTER_AREA)
    return srgb_u8_to_oklab(small.reshape(-1, 3))


class SceneCutDetector:
    """Flags hard cuts: the signature moves much more than its recent norm.

    score = mean OKLab distance between consecutive grid signatures.
    A cut needs score >= ``abs_threshold`` and >= ``ratio`` x the running
    average of normal motion, and cuts are at least ``min_gap`` apart."""

    def __init__(self, abs_threshold: float = 0.09, ratio: float = 3.0, min_gap: float = 0.25) -> None:
        self.abs_threshold = abs_threshold
        self.ratio = ratio
        self.min_gap = min_gap
        self._prev: np.ndarray | None = None
        self._avg = 0.01
        self._last_cut = -1e9
        self.last_score = 0.0

    def reset(self) -> None:
        self._prev = None
        self._avg = 0.01

    def update(self, sig: np.ndarray, now: float) -> bool:
        if self._prev is None or self._prev.shape != sig.shape:
            self._prev = sig
            return False
        score = float(np.mean(np.linalg.norm(sig - self._prev, axis=1)))
        self._prev = sig
        self.last_score = score
        is_cut = score >= self.abs_threshold and score >= self.ratio * self._avg and now - self._last_cut >= self.min_gap
        if is_cut:
            self._last_cut = now
        else:
            self._avg = 0.9 * self._avg + 0.1 * score
        return is_cut

    def is_static(self, threshold: float = 0.004) -> bool:
        return self._prev is not None and self.last_score < threshold


class FlashGuard:
    """Photosensitivity guard: >= ``max_events`` cuts within ``window`` s
    disables fast cut transitions for ``hold`` s (strobing content)."""

    def __init__(self, max_events: int = 3, window: float = 1.0, hold: float = 2.0) -> None:
        self.max_events, self.window, self.hold = max_events, window, hold
        self._events: deque[float] = deque()
        self._active_until = -1e9

    def record(self, now: float) -> None:
        self._events.append(now)
        while self._events and self._events[0] < now - self.window:
            self._events.popleft()
        if len(self._events) >= self.max_events:
            self._active_until = now + self.hold

    def active(self, now: float) -> bool:
        return now < self._active_until
