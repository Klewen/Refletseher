"""Weighted colour clustering in OKLab.

Pipeline: quantise pixels into an OKLab grid (histogram, removes noise and
shrinks ~15k pixels to a few hundred bins) -> deterministic weighted k-means
on the bins (farthest-first initialisation, no randomness) -> merge clusters
that are perceptually indistinguishable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .colorspace import oklab_to_rgb

_L_STEPS = 24
_AB_STEPS = 32
_AB_RANGE = 0.40
MAX_KMEANS_BINS = 600


@dataclass
class Cluster:
    lab: np.ndarray
    weight: float  # share of total *weight* (0..1)
    pixel_share: float  # share of all pixels (unweighted)
    x: float  # weighted horizontal centroid 0..1
    chroma: float
    lightness: float

    @property
    def rgb(self) -> tuple[int, int, int]:
        return oklab_to_rgb(self.lab)


def quantize(lab: np.ndarray, weights: np.ndarray, xs: np.ndarray):
    """Return (bin_lab_means, bin_weight, bin_pixels, bin_x_mean, inverse)."""
    li = np.clip((lab[:, 0] * _L_STEPS).astype(np.int32), 0, _L_STEPS)
    ai = np.clip(((lab[:, 1] + _AB_RANGE) / (2 * _AB_RANGE) * _AB_STEPS).astype(np.int32), 0, _AB_STEPS)
    bi = np.clip(((lab[:, 2] + _AB_RANGE) / (2 * _AB_RANGE) * _AB_STEPS).astype(np.int32), 0, _AB_STEPS)
    key = (li * (_AB_STEPS + 1) + ai) * (_AB_STEPS + 1) + bi
    uniq, inv = np.unique(key, return_inverse=True)
    n = uniq.size
    wsum = np.bincount(inv, weights=weights, minlength=n)
    cnt = np.bincount(inv, minlength=n).astype(np.float64)
    # Means use pixel counts so zero-weight bins still have a valid colour.
    means = np.stack([np.bincount(inv, weights=lab[:, c], minlength=n) / cnt for c in range(3)], axis=1)
    xw = np.bincount(inv, weights=xs * weights, minlength=n)
    xmean = np.where(wsum > 0, xw / np.maximum(wsum, 1e-12), np.bincount(inv, weights=xs, minlength=n) / cnt)
    return means.astype(np.float32), wsum.astype(np.float64), cnt, xmean.astype(np.float32), inv


def weighted_kmeans(points: np.ndarray, weights: np.ndarray, k: int, iters: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic weighted k-means. Returns (centers, labels)."""
    n = points.shape[0]
    k = max(1, min(k, n))
    w = np.maximum(weights, 0.0)
    if w.sum() <= 0:
        w = np.ones(n)
    centers = [points[int(np.argmax(w))]]
    d2 = np.sum((points - centers[0]) ** 2, axis=1)
    for _ in range(1, k):
        score = w * d2
        idx = int(np.argmax(score))
        if score[idx] <= 1e-9:
            break
        centers.append(points[idx])
        d2 = np.minimum(d2, np.sum((points - points[idx]) ** 2, axis=1))
    c = np.array(centers, dtype=np.float32)
    labels = np.zeros(n, dtype=np.int32)
    for _ in range(iters):
        dist = np.sum((points[:, None, :] - c[None, :, :]) ** 2, axis=2)
        new_labels = np.argmin(dist, axis=1).astype(np.int32)
        if _ and np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(c.shape[0]):
            m = labels == j
            ws = w[m].sum()
            if ws > 0:
                c[j] = (points[m] * w[m, None]).sum(axis=0) / ws
    return c, labels


def cluster_colors(
    lab: np.ndarray,
    weights: np.ndarray,
    xs: np.ndarray,
    k: int = 6,
    merge_distance: float = 0.05,
) -> list[Cluster]:
    """Cluster weighted pixels; returns clusters sorted by weight (desc)."""
    total_w = float(weights.sum())
    total_px = float(lab.shape[0])
    if total_w <= 1e-9 or total_px == 0:
        return []
    means, wsum, cnt, xmean, _ = quantize(lab, weights, xs)
    keep = wsum > total_w * 1e-4
    if not np.any(keep):
        keep = wsum > 0
    means, wsum, cnt, xmean = means[keep], wsum[keep], cnt[keep], xmean[keep]
    if means.shape[0] > MAX_KMEANS_BINS:
        # Highly textured frames produce thousands of bins. Fit k-means on the
        # heaviest bins (they carry nearly all the weight), then assign every
        # bin to its nearest centre in a single vectorised pass.
        top = np.argpartition(wsum, -MAX_KMEANS_BINS)[-MAX_KMEANS_BINS:]
        centers, _ = weighted_kmeans(means[top], wsum[top], k)
        labels = np.argmin(np.sum((means[:, None, :] - centers[None, :, :]) ** 2, axis=2), axis=1).astype(np.int32)
    else:
        centers, labels = weighted_kmeans(means, wsum, k)

    clusters: list[dict] = []
    for j in range(centers.shape[0]):
        m = labels == j
        cw = float(wsum[m].sum())
        if cw <= 0:
            continue
        center = (means[m] * wsum[m, None]).sum(axis=0) / cw
        clusters.append(
            {
                "lab": center.astype(np.float32),
                "w": cw,
                "px": float(cnt[m].sum()),
                "x": float((xmean[m] * wsum[m]).sum() / cw),
            }
        )

    # merge perceptually indistinguishable clusters
    merged = True
    while merged and len(clusters) > 1:
        merged = False
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = float(np.linalg.norm(clusters[i]["lab"] - clusters[j]["lab"]))
                if d < merge_distance and (best is None or d < best[0]):
                    best = (d, i, j)
        if best is not None:
            _, i, j = best
            a, b = clusters[i], clusters[j]
            w = a["w"] + b["w"]
            a["lab"] = (a["lab"] * a["w"] + b["lab"] * b["w"]) / w
            a["x"] = (a["x"] * a["w"] + b["x"] * b["w"]) / w
            a["w"], a["px"] = w, a["px"] + b["px"]
            clusters.pop(j)
            merged = True

    out = [
        Cluster(
            lab=c["lab"],
            weight=c["w"] / total_w,
            pixel_share=c["px"] / total_px,
            x=c["x"],
            chroma=float(np.hypot(c["lab"][1], c["lab"][2])),
            lightness=float(c["lab"][0]),
        )
        for c in clusters
    ]
    out.sort(key=lambda c: c.weight, reverse=True)
    return out
