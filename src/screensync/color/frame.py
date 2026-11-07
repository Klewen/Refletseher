"""Per-frame preprocessing: letterbox detection, features and pixel weights."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .colorspace import linear_to_oklab, linear_to_srgb, oklab_to_linear, srgb_u8_to_linear, srgb_to_linear
from .settings import AnalysisSettings, SpatialWeighting

Crop = tuple[int, int, int, int]  # top, bottom, left, right (pixels removed)


def detect_bars(rgb: np.ndarray, threshold: int = 20, fraction: float = 0.985) -> Crop:
    """Count fully black rows/columns at each edge of a small RGB frame."""
    h, w = rgb.shape[:2]
    dark = rgb.max(axis=2) < threshold
    rows = dark.mean(axis=1) >= fraction
    cols = dark.mean(axis=0) >= fraction

    def run(mask: np.ndarray) -> int:
        idx = np.flatnonzero(~mask)
        return int(idx[0]) if idx.size else mask.size

    top, bottom = run(rows), run(rows[::-1])
    left, right = run(cols), run(cols[::-1])
    if top + bottom >= h or left + right >= w:  # entire frame black
        return (0, 0, 0, 0)
    return top, bottom, left, right


class LetterboxTracker:
    """Temporal filter: a bar is only accepted if it persisted for the whole
    window (minimum over history), so dark scenes are not cropped away."""

    def __init__(self, window: int = 24, max_fraction: float = 0.3) -> None:
        self._hist: deque[Crop] = deque(maxlen=window)
        self.max_fraction = max_fraction
        self.window = window

    def reset(self) -> None:
        self._hist.clear()

    def update(self, rgb: np.ndarray) -> Crop:
        h, w = rgb.shape[:2]
        self._hist.append(detect_bars(rgb))
        if len(self._hist) < min(6, self.window):
            return (0, 0, 0, 0)
        arr = np.array(self._hist)
        top, bottom, left, right = (int(v) for v in arr.min(axis=0))
        mh, mw = int(h * self.max_fraction), int(w * self.max_fraction)
        top, bottom = (top if top <= mh else 0), (bottom if bottom <= mh else 0)
        left, right = (left if left <= mw else 0), (right if right <= mw else 0)
        return top, bottom, left, right


@dataclass
class FrameFeatures:
    rgb: np.ndarray  # cropped (h, w, 3) uint8
    lab: np.ndarray  # (n, 3) OKLab
    L: np.ndarray  # (n,)
    C: np.ndarray  # (n,) chroma
    xs: np.ndarray  # (n,) 0..1 column position
    ys: np.ndarray  # (n,) 0..1 row position
    h: int
    w: int
    crop: Crop

    @property
    def mean_L(self) -> float:
        return float(self.L.mean()) if self.L.size else 0.0


def compute_features(rgb: np.ndarray, crop: Crop = (0, 0, 0, 0)) -> FrameFeatures:
    top, bottom, left, right = crop
    h0, w0 = rgb.shape[:2]
    cropped = rgb[top : h0 - bottom if bottom else h0, left : w0 - right if right else w0]
    if cropped.size == 0:
        cropped = rgb
    h, w = cropped.shape[:2]
    lab = linear_to_oklab(srgb_u8_to_linear(np.ascontiguousarray(cropped)).reshape(-1, 3))
    C = np.sqrt(lab[:, 1] ** 2 + lab[:, 2] ** 2)
    yy, xx = np.mgrid[0:h, 0:w]
    xs = ((xx.reshape(-1) + 0.5) / w).astype(np.float32)
    ys = ((yy.reshape(-1) + 0.5) / h).astype(np.float32)
    return FrameFeatures(cropped, lab, lab[:, 0].copy(), C, xs, ys, h, w, crop)


def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / max(1e-6, e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def pixel_weights(f: FrameFeatures, s: AnalysisSettings, saturation_bias: float, mask: np.ndarray | None = None) -> np.ndarray:
    """Importance of every pixel for colour extraction.

    * dark pixels (below the black level) fade to zero weight,
    * chroma weighting favours colourful pixels by ``saturation_bias``,
    * subtitle guard: bright, colourless pixels in the bottom band get ~0,
    * optional centre / edge emphasis.
    """
    bl = s.black_level
    w = smoothstep(bl, bl + 0.10, f.L)
    w *= (1.0 - saturation_bias) + saturation_bias * np.minimum(1.0, f.C / 0.13)
    if s.subtitle_guard:
        band = f.ys >= 1.0 - s.subtitle_band
        textlike = (f.C < 0.06) & (f.L > 0.55)
        w = np.where(band & textlike, w * 0.03, w)
    if s.spatial_weighting == SpatialWeighting.CENTER:
        d2 = (f.xs - 0.5) ** 2 + (f.ys - 0.5) ** 2
        w *= 0.25 + 0.75 * np.exp(-d2 / (2 * 0.28**2))
    elif s.spatial_weighting == SpatialWeighting.EDGES:
        edge = np.minimum(np.minimum(f.xs, 1 - f.xs), np.minimum(f.ys, 1 - f.ys))
        w *= 0.3 + 0.7 * np.clip(1.0 - edge / 0.25, 0.0, 1.0)
    if mask is not None:
        w = np.where(mask, w, 0.0)
    return w.astype(np.float32)


def brightness_envelope(mean_L: float, strength: float = 1.0) -> float:
    """How bright the keyboard may be for a scene of average lightness
    ``mean_L`` (OKLab, 0..1). Dark scenes stay dark; normal scenes -> 1."""
    raw = float(np.clip((mean_L - 0.03) / 0.30, 0.0, 1.0)) ** 0.75
    return 1.0 - strength * (1.0 - raw)


def dim_lab(lab: np.ndarray, factor: float) -> np.ndarray:
    """Scale the sRGB-encoded value of a colour by ``factor`` (0..1)."""
    lab = np.asarray(lab, dtype=np.float32)
    srgb = linear_to_srgb(np.clip(oklab_to_linear(lab), 0, 1)) * float(np.clip(factor, 0.0, 1.0))
    return linear_to_oklab(srgb_to_linear(srgb))
