"""Synthetic-frame tests for the colour engine (no screen capture needed)."""

from __future__ import annotations

import numpy as np
import pytest

from refletseher.capture import synthetic as S
from refletseher.color.colorspace import delta_e, oklab_to_rgb, oklab_to_srgb_u8, rgb_to_oklab, srgb_u8_to_oklab
from refletseher.color.extractors import AdaptiveClassifier, ColorAnalyzer
from refletseher.color.frame import LetterboxTracker, compute_features, detect_bars
from refletseher.color.scene import FlashGuard, SceneCutDetector, signature
from refletseher.color.settings import AnalysisSettings, SyncMode

RED, GREEN, BLUE, YELLOW = (230, 30, 30), (30, 200, 60), (40, 60, 230), (240, 220, 40)


def analyze(img, mode, **kw):
    return ColorAnalyzer(AnalysisSettings(mode=mode, **kw)).analyze(compute_features(img))


def zones_rgb(res):
    return [oklab_to_rgb(z) for z in res.zones]


def close(a, b, tol=0.03):
    return float(delta_e(rgb_to_oklab(a), rgb_to_oklab(b))) < tol


# ------------------------------------------------------------ colour space
def test_oklab_roundtrip():
    rgb = np.random.default_rng(1).integers(0, 256, (500, 3)).astype(np.uint8)
    back = oklab_to_srgb_u8(srgb_u8_to_oklab(rgb))
    assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 1


def test_gamut_clip_keeps_hue():
    lab = rgb_to_oklab((255, 0, 0)).copy()
    lab[1:] *= 1.6  # out of sRGB
    r, g, b = oklab_to_rgb(lab)
    assert r > 200 and g < 60 and b < 60


# --------------------------------------------------------------- dominant
@pytest.mark.parametrize("color", [(220, 20, 20), (20, 40, 230), (30, 200, 60), (240, 240, 240)])
def test_dominant_solid_colors(color):
    res = analyze(S.solid(color), SyncMode.DOMINANT)
    assert all(close(z, color) for z in zones_rgb(res))


def test_dominant_prefers_large_area():
    img = S.blobs((30, 60, 200), [((230, 30, 30), 0.5, 0.5, 0.15)])
    res = analyze(img, SyncMode.DOMINANT)
    assert close(zones_rgb(res)[0], (30, 60, 200))


def test_black_frame_gives_black():
    for mode in SyncMode:
        res = analyze(S.solid((0, 0, 0)), mode)
        assert all(max(z) <= 2 for z in zones_rgb(res)), mode


def test_black_pixels_do_not_dominate():
    """60% black + 40% blue must produce blue, not black/grey."""
    img = S.solid((0, 0, 0))
    img[:, :64] = (40, 60, 230)
    res = analyze(img, SyncMode.DOMINANT)
    r, g, b = zones_rgb(res)[0]
    assert b > 100 and b > r * 2


# ---------------------------------------------------------------- palette
def test_four_color_extraction_left_to_right():
    res = analyze(S.vertical_bands([RED, GREEN, BLUE, YELLOW]), SyncMode.PALETTE)
    got = zones_rgb(res)
    for z, expected in zip(got, [RED, GREEN, BLUE, YELLOW]):
        assert close(z, expected), (got, expected)


def test_film_scene_four_meaningful_colors():
    """Red flowers, light-blue sky, cream wall, burgundy details."""
    sky, red, cream, bordo = (200, 230, 250), (210, 30, 40), (235, 225, 200), (110, 20, 40)
    img = S.blobs(sky, [(red, 0.2, 0.7, 0.25), (cream, 0.75, 0.6, 0.35), (bordo, 0.5, 0.9, 0.12)])
    got = zones_rgb(analyze(img, SyncMode.PALETTE))
    for expected in (sky, red, cream, bordo):
        assert any(close(z, expected, 0.04) for z in got), (expected, got)


def test_single_color_scene_no_random_colors():
    noisy = np.clip(S.solid((40, 120, 200)).astype(int) + np.random.default_rng(0).integers(-12, 12, (90, 160, 3)), 0, 255)
    res = analyze(noisy.astype(np.uint8), SyncMode.PALETTE)
    z = res.zones
    assert float(np.max(delta_e(z, z[0]))) < 0.02


def test_saturated_multicolor_scene():
    img = S.vertical_bands([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255)])
    res = analyze(img, SyncMode.PALETTE)
    z = res.zones
    dists = [float(delta_e(z[i], z[j])) for i in range(4) for j in range(i + 1, 4)]
    assert min(dists) > 0.2


def test_tiny_objects_ignored():
    """A 0.2% speck (cursor / small UI element) must not take a zone."""
    img = S.solid((30, 60, 200))
    img[10:12, 10:12] = (255, 255, 0)
    got = zones_rgb(analyze(img, SyncMode.PALETTE))
    assert all(close(z, (30, 60, 200)) for z in got)


def test_subtitle_strip_rejected():
    img = S.with_subtitle(S.solid((30, 60, 200)))
    for mode in (SyncMode.DOMINANT, SyncMode.PALETTE, SyncMode.CINEMATIC):
        got = zones_rgb(analyze(img, mode))
        assert all(close(z, (30, 60, 200)) for z in got), (mode, got)


def test_deterministic_output():
    img = S.moving_scene(3.3)
    a = analyze(img, SyncMode.PALETTE).zones
    b = analyze(img, SyncMode.PALETTE).zones
    assert np.array_equal(a, b)


# ---------------------------------------------------------------- spatial
def test_spatial_maps_four_regions():
    res = analyze(S.vertical_bands([RED, GREEN, BLUE, YELLOW]), SyncMode.SPATIAL, neighbor_blend=0.0)
    for z, expected in zip(zones_rgb(res), [RED, GREEN, BLUE, YELLOW]):
        assert close(z, expected, 0.04)
    assert res.reorderable is False


def test_spatial_dark_side_is_dark():
    img = S.vertical_bands([(0, 0, 0), (0, 0, 0), BLUE, BLUE])
    got = zones_rgb(analyze(img, SyncMode.SPATIAL))
    assert max(got[0]) < 20 and got[3][2] > 150


# -------------------------------------------------------------- cinematic
def test_cinematic_dark_scene_keeps_accent_but_stays_dim():
    img = S.blobs((4, 4, 6), [((255, 30, 20), 0.7, 0.4, 0.08)])
    got = zones_rgb(analyze(img, SyncMode.CINEMATIC))
    assert any(r > 60 and r > 3 * g for r, g, _ in got)  # red accent survives
    assert all(max(z) < 200 for z in got)  # but the scene is not lit up


def test_cinematic_bright_scene_full_brightness():
    got = zones_rgb(analyze(S.vertical_bands([RED, BLUE]), SyncMode.CINEMATIC))
    assert max(max(z) for z in got) > 200


# --------------------------------------------------------------- adaptive
@pytest.mark.parametrize(
    "img,label",
    [
        (S.solid((0, 0, 0)), AdaptiveClassifier.DARK),
        (S.blobs((3, 3, 3), [((255, 0, 0), 0.5, 0.5, 0.05)]), AdaptiveClassifier.DARK),
        (S.solid((20, 160, 40)), AdaptiveClassifier.MONO),
        (S.vertical_bands([RED, GREEN, BLUE, YELLOW]), AdaptiveClassifier.SPATIAL),
        # many colours, but every screen strip contains all of them -> palette
        (S.horizontal_bands([RED, GREEN, BLUE, YELLOW]), AdaptiveClassifier.MULTI),
    ],
)
def test_adaptive_classification(img, label):
    got, _ = AdaptiveClassifier().classify(compute_features(img), AnalysisSettings())
    assert got == label


def test_adaptive_hysteresis():
    c = AdaptiveClassifier(hold=3)
    assert c.update("dark") == "dark"
    assert c.update("monochrome") == "dark"
    assert c.update("monochrome") == "dark"
    assert c.update("monochrome") == "monochrome"
    assert c.update("dark", force=True) == "dark"  # scene cut switches immediately


# --------------------------------------------------------------- letterbox
def test_letterbox_detection_and_temporal_guard():
    img = S.with_letterbox(S.solid((200, 50, 50)), 0.12)
    top, bottom, left, right = detect_bars(img)
    assert top == bottom == int(90 * 0.12) and left == right == 0
    tr = LetterboxTracker(window=8)
    for _ in range(8):
        crop = tr.update(img)
    assert crop[0] == int(90 * 0.12)
    # a dark scene inside the bars must not be cropped away
    dark = S.with_letterbox(S.solid((5, 5, 5)), 0.12)
    for _ in range(3):
        crop = tr.update(dark)
    assert crop[0] <= int(90 * 0.12)


def test_letterbox_does_not_change_colors():
    res = analyze(S.with_letterbox(S.vertical_bands([RED, BLUE])), SyncMode.PALETTE)
    got = zones_rgb(res)
    assert any(close(z, RED) for z in got) and any(close(z, BLUE) for z in got)


# ------------------------------------------------------------ scene change
def test_scene_cut_detection():
    d = SceneCutDetector()
    red, blue = signature(S.solid(RED)), signature(S.solid(BLUE))
    t = 0.0
    for _ in range(5):
        assert not d.update(red, t)
        t += 0.1
    assert d.update(blue, t)
    assert not d.update(blue, t + 0.1)
    assert d.is_static()


def test_slow_motion_is_not_a_cut():
    d = SceneCutDetector()
    cuts = sum(d.update(signature(S.moving_scene(i * 0.1)), i * 0.1) for i in range(60))
    assert cuts == 0


def test_flash_guard():
    g = FlashGuard(max_events=3, window=1.0, hold=2.0)
    for t in (0.0, 0.3, 0.6):
        g.record(t)
    assert g.active(0.7) and not g.active(3.0)
