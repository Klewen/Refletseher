"""Vectorised colour-space conversions (sRGB <-> linear <-> OKLab).

OKLab (Björn Ottosson, 2020) is used as the perceptual working space: it is
as cheap as a 3x3 matrix + cube root, has far better hue linearity than
CIELAB for saturated colours (no blue -> purple drift when interpolating),
and Euclidean distance in OKLab is a good perceptual difference metric
("deltaE_ok"; 0.02 ~ just noticeable, 0.1 ~ clearly different).
"""

from __future__ import annotations

import numpy as np

_SRGB_TO_LINEAR_LUT = np.array(
    [((i / 255.0) / 12.92) if i / 255.0 <= 0.04045 else (((i / 255.0) + 0.055) / 1.055) ** 2.4 for i in range(256)],
    dtype=np.float32,
)

_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float32,
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float32,
)
_M2_INV = np.linalg.inv(_M2.astype(np.float64)).astype(np.float32)
_M1_INV = np.linalg.inv(_M1.astype(np.float64)).astype(np.float32)


def srgb_u8_to_linear(rgb: np.ndarray) -> np.ndarray:
    """uint8 sRGB (..., 3) -> float32 linear RGB in 0..1 (LUT, very fast)."""
    return _SRGB_TO_LINEAR_LUT[rgb]


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """float sRGB 0..1 -> linear."""
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(np.asarray(lin, dtype=np.float32), 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055).astype(np.float32)


def linear_to_oklab(lin: np.ndarray) -> np.ndarray:
    lms = lin @ _M1.T
    lms = np.cbrt(np.maximum(lms, 0.0))
    return (lms @ _M2.T).astype(np.float32)


def oklab_to_linear(lab: np.ndarray) -> np.ndarray:
    lms = np.asarray(lab, dtype=np.float32) @ _M2_INV.T
    return (lms**3) @ _M1_INV.T


def srgb_u8_to_oklab(rgb: np.ndarray) -> np.ndarray:
    return linear_to_oklab(srgb_u8_to_linear(np.asarray(rgb, dtype=np.uint8)))


def oklab_to_srgb_u8(lab: np.ndarray) -> np.ndarray:
    """OKLab -> uint8 sRGB with chroma-preserving gamut clipping."""
    lab = np.asarray(lab, dtype=np.float32)
    lin = oklab_to_linear(lab)
    if np.any(lin < -1e-4) or np.any(lin > 1.0 + 1e-4):
        lin = _gamut_clip(lab)
    srgb = linear_to_srgb(lin)
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def _gamut_clip(lab: np.ndarray) -> np.ndarray:
    """Reduce chroma (keep L and hue) until each colour fits into sRGB.

    Vectorised bisection on the chroma scale factor for all colours at once."""
    flat = lab.reshape(-1, 3).astype(np.float32)
    L = np.clip(flat[:, 0], 0.0, 1.0)
    ab = flat[:, 1:]
    lo = np.zeros(len(flat), np.float32)
    hi = np.ones(len(flat), np.float32)
    for _ in range(14):
        mid = (lo + hi) * 0.5
        cand = np.concatenate([L[:, None], ab * mid[:, None]], axis=1)
        lin = oklab_to_linear(cand)
        ok = np.all((lin >= -1e-5) & (lin <= 1.0 + 1e-5), axis=1)
        lo = np.where(ok, mid, lo)
        hi = np.where(ok, hi, mid)
    best = np.concatenate([L[:, None], ab * lo[:, None]], axis=1)
    return np.clip(oklab_to_linear(best), 0.0, 1.0).reshape(lab.shape)


def rgb_to_oklab(color: tuple[int, int, int]) -> np.ndarray:
    return srgb_u8_to_oklab(np.array(color, dtype=np.uint8))


def oklab_to_rgb(lab: np.ndarray) -> tuple[int, int, int]:
    r, g, b = oklab_to_srgb_u8(np.asarray(lab, dtype=np.float32).reshape(3))
    return int(r), int(g), int(b)


def delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Euclidean OKLab distance (broadcasting)."""
    d = np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32)
    return np.sqrt(np.sum(d * d, axis=-1))


def chroma(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float32)
    return np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)


def scale_chroma(lab: np.ndarray, factor: float) -> np.ndarray:
    out = np.array(lab, dtype=np.float32, copy=True)
    out[..., 1:] *= factor
    return out
