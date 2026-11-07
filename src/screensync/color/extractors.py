"""Colour extraction algorithms: frame features -> four zone targets (OKLab).

All algorithms are deterministic (no random initialisation) so that the
same frame always yields the same colours, which keeps the keyboard calm
and makes the behaviour testable with synthetic frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .clustering import Cluster, cluster_colors
from .colorspace import delta_e
from .frame import FrameFeatures, brightness_envelope, dim_lab, pixel_weights
from .settings import AnalysisSettings, SyncMode

BLACK_LAB = np.zeros(3, dtype=np.float32)


@dataclass
class SceneStats:
    mean_L: float = 0.0
    bright_fraction: float = 0.0
    colorfulness: float = 0.0
    dominant_share: float = 0.0
    distinct_colors: int = 0
    spatial_variation: float = 0.0
    label: str = ""


@dataclass
class AnalysisResult:
    zones: np.ndarray  # (4, 3) OKLab targets
    mode: SyncMode  # algorithm actually used (adaptive resolves to a sub mode)
    reorderable: bool  # zones may be permuted for temporal stability
    palette: list[Cluster] = field(default_factory=list)
    stats: SceneStats = field(default_factory=SceneStats)


def _bright_fraction(f: FrameFeatures, s: AnalysisSettings) -> float:
    return float(np.mean(f.L > s.black_level + 0.04)) if f.L.size else 0.0


def _stats(f: FrameFeatures, s: AnalysisSettings, clusters: list[Cluster]) -> SceneStats:
    st = SceneStats(mean_L=f.mean_L, bright_fraction=_bright_fraction(f, s))
    st.colorfulness = float(np.mean(f.C)) if f.C.size else 0.0
    if clusters:
        st.dominant_share = clusters[0].weight
        distinct = [clusters[0]]
        for c in clusters[1:]:
            if c.weight >= 0.10 and min(float(delta_e(c.lab, d.lab)) for d in distinct) >= 0.10:
                distinct.append(c)
        st.distinct_colors = len(distinct)
    return st


def _allocate(selected: list[Cluster], weights: list[float]) -> list[int]:
    """Distribute 4 zones over the selected colours proportionally to weight
    (largest remainder, each colour >= 1 zone), ordered left to right."""
    n = len(selected)
    order = sorted(range(n), key=lambda i: selected[i].x)
    total = sum(weights) or 1.0
    quotas = [weights[i] / total * 4 for i in range(n)]
    alloc = [1] * n
    remaining = 4 - n
    while remaining > 0:
        i = max(range(n), key=lambda j: quotas[j] - alloc[j])
        alloc[i] += 1
        remaining -= 1
    zones: list[int] = []
    for i in order:
        zones += [i] * alloc[i]
    return zones


def _select(clusters: list[Cluster], scores: list[float], min_distance: float, limit: int = 4) -> list[int]:
    order = sorted(range(len(clusters)), key=lambda i: scores[i], reverse=True)
    chosen: list[int] = []
    for i in order:
        if scores[i] <= 0:
            continue
        if all(float(delta_e(clusters[i].lab, clusters[j].lab)) >= min_distance for j in chosen):
            chosen.append(i)
        if len(chosen) == limit:
            break
    return chosen


def _light_factor(L: float) -> float:
    # near black and near white are less "characteristic" than mid tones
    return 0.45 + 0.55 * float(np.clip(1.0 - abs(L - 0.68) / 0.6, 0.0, 1.0))


# ------------------------------------------------------------------ dominant
def extract_dominant(f: FrameFeatures, s: AnalysisSettings) -> AnalysisResult:
    w = pixel_weights(f, s, saturation_bias=0.35)
    clusters = cluster_colors(f.lab, w, f.xs, k=5, merge_distance=0.06)
    st = _stats(f, s, clusters)
    st.label = "dominant"
    if not clusters:
        return AnalysisResult(np.zeros((4, 3), np.float32), SyncMode.DOMINANT, True, [], st)
    scores = [c.weight * (0.6 + 0.8 * min(1.0, c.chroma / 0.15)) for c in clusters]
    top = clusters[int(np.argmax(scores))]
    color = dim_lab(top.lab, brightness_envelope(f.mean_L, 1.0))
    return AnalysisResult(np.tile(color, (4, 1)), SyncMode.DOMINANT, True, clusters, st)


# ------------------------------------------------------------------- palette
def extract_palette(f: FrameFeatures, s: AnalysisSettings) -> AnalysisResult:
    w = pixel_weights(f, s, saturation_bias=0.65)
    clusters = cluster_colors(f.lab, w, f.xs, k=8, merge_distance=0.04)
    st = _stats(f, s, clusters)
    st.label = "palette"
    if not clusters:
        return AnalysisResult(np.zeros((4, 3), np.float32), SyncMode.PALETTE, True, [], st)
    scores = [
        (c.weight**0.55) * (0.35 + min(1.0, c.chroma / 0.14)) * _light_factor(c.lightness)
        if c.weight >= s.min_cluster_share
        else 0.0
        for c in clusters
    ]
    chosen = _select(clusters, scores, s.min_palette_distance)
    if not chosen:
        chosen = [0]
    sel = [clusters[i] for i in chosen]
    zones_idx = _allocate(sel, [c.weight for c in sel])
    env = brightness_envelope(f.mean_L, 0.8)
    zones = np.stack([dim_lab(sel[i].lab, env) for i in zones_idx])
    return AnalysisResult(zones.astype(np.float32), SyncMode.PALETTE, True, sel, st)


# ------------------------------------------------------------------- spatial
def strip_colors(f: FrameFeatures, s: AnalysisSettings, overlap: float = 0.04) -> tuple[np.ndarray, list[float]]:
    zones = np.zeros((4, 3), np.float32)
    keys: list[float] = []
    for i in range(4):
        lo, hi = i / 4 - overlap, (i + 1) / 4 + overlap
        m = (f.xs >= lo) & (f.xs < hi)
        key = float(f.L[m].mean()) if np.any(m) else 0.0
        keys.append(key)
        w = pixel_weights(f, s, saturation_bias=0.45, mask=m)
        clusters = cluster_colors(f.lab[m], w[m], f.xs[m], k=3, merge_distance=0.06)
        if not clusters:
            continue
        scores = [c.weight * (0.6 + 0.8 * min(1.0, c.chroma / 0.15)) for c in clusters]
        top = clusters[int(np.argmax(scores))]
        zones[i] = dim_lab(top.lab, brightness_envelope(key, 1.0))
    return zones, keys


def extract_spatial(f: FrameFeatures, s: AnalysisSettings) -> AnalysisResult:
    zones, _ = strip_colors(f, s)
    b = float(np.clip(s.neighbor_blend, 0.0, 0.3))
    if b > 0:
        blended = zones.copy()
        for i in range(4):
            nb = [j for j in (i - 1, i + 1) if 0 <= j < 4]
            blended[i] = zones[i] * (1 - b * len(nb)) + sum(zones[j] for j in nb) * b
        zones = blended
    st = SceneStats(mean_L=f.mean_L, bright_fraction=_bright_fraction(f, s), label="spatial")
    st.spatial_variation = float(np.mean(delta_e(zones[1:], zones[:-1])))
    return AnalysisResult(zones.astype(np.float32), SyncMode.SPATIAL, False, [], st)


# ----------------------------------------------------------------- cinematic
def extract_cinematic(f: FrameFeatures, s: AnalysisSettings) -> AnalysisResult:
    """Characteristic colours with accent preservation.

    Colourful clusters are favoured strongly; small but saturated accents
    (a red light in a dark scene) survive if they cover >= accent_min_share
    of the frame. The overall brightness follows the scene key, so a dark
    scene stays dim, but accents keep a visible floor."""
    w = pixel_weights(f, s, saturation_bias=0.9)
    clusters = cluster_colors(f.lab, w, f.xs, k=8, merge_distance=0.06)
    st = _stats(f, s, clusters)
    st.label = "cinematic"
    if not clusters:
        return AnalysisResult(np.zeros((4, 3), np.float32), SyncMode.CINEMATIC, True, [], st)

    def qualifies(c: Cluster) -> bool:
        accent = c.chroma >= 0.08 and c.pixel_share >= s.accent_min_share
        return accent or c.weight >= s.min_cluster_share

    scores = [
        (c.weight**0.4) * (0.2 + min(1.0, c.chroma / 0.12)) ** 1.5 * (0.5 + 0.5 * min(1.0, c.lightness / 0.5))
        if qualifies(c)
        else 0.0
        for c in clusters
    ]
    chosen = _select(clusters, scores, s.min_palette_distance) or [0]
    sel = [clusters[i] for i in chosen]
    env = brightness_envelope(f.mean_L, 0.9)
    colors = []
    for c in sel:
        factor = env
        if c.chroma >= 0.08:
            floor = 0.35 * min(1.0, (c.pixel_share / 0.01) ** 0.5)
            factor = max(env, floor)
        colors.append(dim_lab(c.lab, factor))
    # allocate by visual score rather than raw area so accents get a zone
    zones_idx = _allocate(sel, [scores[i] for i in chosen])
    zones = np.stack([colors[i] for i in zones_idx])
    return AnalysisResult(zones.astype(np.float32), SyncMode.CINEMATIC, True, sel, st)


# ------------------------------------------------------------------ adaptive
class AdaptiveClassifier:
    """Deterministic, rule based scene classifier with hysteresis.

    dark       -> cinematic (keeps darkness, preserves accents)
    monochrome -> dominant  (never invents four random colours)
    spatial    -> spatial   (left/right parts of the screen clearly differ)
    multicolor -> palette
    """

    DARK, MONO, SPATIAL, MULTI = "dark", "monochrome", "spatial", "multicolor"
    _MODE = {DARK: SyncMode.CINEMATIC, MONO: SyncMode.DOMINANT, SPATIAL: SyncMode.SPATIAL, MULTI: SyncMode.PALETTE}

    def __init__(self, hold: int = 4) -> None:
        self.hold = hold
        self.current: str | None = None
        self._candidate: str | None = None
        self._count = 0

    def classify(self, f: FrameFeatures, s: AnalysisSettings) -> tuple[str, SceneStats]:
        w = pixel_weights(f, s, saturation_bias=0.5)
        clusters = cluster_colors(f.lab, w, f.xs, k=6, merge_distance=0.06)
        st = _stats(f, s, clusters)
        if st.bright_fraction < 0.06 or st.mean_L < 0.10:
            label = self.DARK
        elif st.dominant_share >= 0.62 and st.distinct_colors <= 1:
            label = self.MONO
        else:
            strips, _ = strip_colors(f, s, overlap=0.0)
            st.spatial_variation = float(np.mean(delta_e(strips[1:], strips[:-1])))
            label = self.SPATIAL if st.spatial_variation >= 0.16 else self.MULTI
        st.label = label
        return label, st

    def update(self, label: str, force: bool = False) -> str:
        if self.current is None or force:
            self.current, self._candidate, self._count = label, None, 0
            return self.current
        if label == self.current:
            self._candidate, self._count = None, 0
        elif label == self._candidate:
            self._count += 1
            if self._count >= self.hold:
                self.current, self._candidate, self._count = label, None, 0
        else:
            self._candidate, self._count = label, 1
        return self.current


EXTRACTORS = {
    SyncMode.DOMINANT: extract_dominant,
    SyncMode.PALETTE: extract_palette,
    SyncMode.SPATIAL: extract_spatial,
    SyncMode.CINEMATIC: extract_cinematic,
}


class ColorAnalyzer:
    """Stateful front-end used by the sync engine."""

    def __init__(self, settings: AnalysisSettings | None = None) -> None:
        self.settings = settings or AnalysisSettings()
        self.adaptive = AdaptiveClassifier()

    def analyze(self, f: FrameFeatures, scene_cut: bool = False) -> AnalysisResult:
        s = self.settings
        if s.mode == SyncMode.ADAPTIVE:
            label, st = self.adaptive.classify(f, s)
            current = self.adaptive.update(label, force=scene_cut)
            res = EXTRACTORS[AdaptiveClassifier._MODE[current]](f, s)
            res.stats.label = current
            res.stats.spatial_variation = st.spatial_variation
            return res
        return EXTRACTORS[s.mode](f, s)
