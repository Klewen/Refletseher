"""Transition engine: temporal filtering, hysteresis and smooth fades.

Stages for each analysed frame:
 1. temporal matching (palette modes): permute new colours onto the zones
    whose previous colour is closest -> no zone hopping,
 2. EMA on targets (``smoothing``) to remove detection noise,
 3. hysteresis (``sensitivity``): a zone's target only moves when the
    filtered colour drifts further than a perceptual threshold,
 4. time-based exponential approach in OKLab (``transition_speed``),
    independent of frame rate; scene cuts temporarily use a short time
    constant so cuts are followed without lag (unless the flash guard is
    active because the content is strobing).
"""

from __future__ import annotations

import math

import numpy as np

from ..color.colorspace import delta_e
from ..color.scene import FlashGuard
from ..color.settings import TransitionSettings
from .matching import best_assignment

CUT_WINDOW_S = 0.35
SNAP_DISTANCE = 0.002


def tau_for_speed(speed: int) -> float:
    """0 -> 1.4 s, 100 -> 0.06 s (log scale)."""
    s = min(max(speed, 0), 100) / 100.0
    return 1.4 * (0.06 / 1.4) ** s


def threshold_for_sensitivity(sensitivity: int) -> float:
    """0 -> 0.10 (only big changes), 100 -> 0.004 (tiny changes)."""
    s = min(max(sensitivity, 0), 100) / 100.0
    return 0.10 * (0.004 / 0.10) ** s


class TransitionEngine:
    def __init__(self, settings: TransitionSettings | None = None) -> None:
        self.settings = settings or TransitionSettings()
        self.current: np.ndarray | None = None
        self.target: np.ndarray | None = None
        self.filtered: np.ndarray | None = None
        self._last_step: float | None = None
        self._cut_until = -1e9
        self.flash_guard = FlashGuard()
        self.cuts = 0
        self.swaps_prevented = 0

    def reset(self, start: np.ndarray | None = None) -> None:
        self.current = None if start is None else np.array(start, dtype=np.float32)
        self.target = None if start is None else np.array(start, dtype=np.float32)
        self.filtered = None if start is None else np.array(start, dtype=np.float32)
        self._last_step = None
        self._cut_until = -1e9

    @property
    def tau(self) -> float:
        return tau_for_speed(self.settings.transition_speed)

    def set_targets(self, new: np.ndarray, now: float, reorderable: bool = True, cut: bool = False) -> None:
        new = np.asarray(new, dtype=np.float32).reshape(4, 3)
        if self.filtered is None or self.target is None:
            self.filtered = new.copy()
            self.target = new.copy()
            if self.current is None:
                self.current = np.zeros((4, 3), np.float32)  # fade in from black
            return
        if reorderable:
            perm = best_assignment(self.filtered, new)
            if perm != (0, 1, 2, 3):
                self.swaps_prevented += 1
            new = new[list(perm)]
        s = self.settings
        fast_cut = cut and s.scene_cut_fast
        if cut and s.flash_guard:
            self.flash_guard.record(now)
            if self.flash_guard.active(now):
                fast_cut = False
        if fast_cut:
            self.cuts += 1
            self.filtered = new.copy()
            self.target = new.copy()
            self._cut_until = now + CUT_WINDOW_S
            return
        alpha = 1.0 - 0.85 * (min(max(s.smoothing, 0), 100) / 100.0)
        self.filtered = self.filtered + alpha * (new - self.filtered)
        thr = threshold_for_sensitivity(s.sensitivity)
        moved = delta_e(self.filtered, self.target) > thr
        self.target[moved] = self.filtered[moved]

    def step(self, now: float) -> np.ndarray | None:
        if self.target is None:
            return None
        if self.current is None:
            self.current = self.target.copy()
        if self._last_step is None:
            self._last_step = now
            return self.current
        dt = max(0.0, min(0.5, now - self._last_step))
        self._last_step = now
        tau = self.tau
        if now < self._cut_until:
            tau = min(tau, 0.10)
        k = 1.0 - math.exp(-dt / max(tau, 1e-3))
        self.current = self.current + (self.target - self.current) * k
        close = delta_e(self.current, self.target) < SNAP_DISTANCE
        self.current[close] = self.target[close]
        return self.current

    def converged(self) -> bool:
        if self.current is None or self.target is None:
            return True
        return bool(np.all(delta_e(self.current, self.target) < SNAP_DISTANCE))
