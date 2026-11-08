from __future__ import annotations

import numpy as np

from refletseher.color.colorspace import delta_e, rgb_to_oklab
from refletseher.color.settings import OutputSettings, TransitionSettings
from refletseher.sync.matching import best_assignment
from refletseher.sync.output import OutputDeadband, finalize, scale_zone_colors
from refletseher.sync.transition import TransitionEngine, tau_for_speed, threshold_for_sensitivity

RED, BLUE, GREEN, YELLOW = (255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 0)


def lab4(*colors):
    return np.stack([rgb_to_oklab(c) for c in colors])


def run(engine, seconds, dt=1 / 30, t0=0.0):
    t = t0
    path = []
    while t < t0 + seconds:
        t += dt
        path.append(engine.step(t).copy())
    return t, path


def test_smooth_interpolation_red_to_blue():
    e = TransitionEngine(TransitionSettings(transition_speed=50, smoothing=0, sensitivity=100))
    e.reset(lab4(RED, RED, RED, RED))
    e.set_targets(lab4(BLUE, BLUE, BLUE, BLUE), 0.0)
    e.step(0.0)
    t, path = run(e, 2.0)
    d = [float(delta_e(p[0], lab4(BLUE)[0])) for p in path]
    assert all(b <= a + 1e-6 for a, b in zip(d, d[1:]))  # monotonic approach, no overshoot
    jumps = [float(delta_e(a[0], b[0])) for a, b in zip(path, path[1:])]
    assert max(jumps) < 0.12  # no sudden jump at 30 Hz
    assert d[-1] < 0.01


def test_bounded_latency_on_scene_cut():
    e = TransitionEngine(TransitionSettings(transition_speed=0, smoothing=80))  # slowest settings
    e.reset(lab4(RED, RED, RED, RED))
    e.step(0.0)
    e.set_targets(lab4(BLUE, BLUE, BLUE, BLUE), 0.0, cut=True)
    _, path = run(e, 0.5)
    assert float(delta_e(path[-1][0], lab4(BLUE)[0])) < 0.02


def test_flash_guard_disables_fast_cuts():
    e = TransitionEngine(TransitionSettings(transition_speed=0, smoothing=0, sensitivity=100))
    e.reset(lab4(RED, RED, RED, RED))
    t = 0.0
    e.step(t)
    for i in range(4):  # strobing: 4 cuts in 0.6 s
        t += 0.15
        e.set_targets(lab4(*(BLUE if i % 2 == 0 else RED,) * 4), t, cut=True)
        e.step(t)
    assert e.flash_guard.active(t)
    assert e.cuts < 4


def test_hysteresis_ignores_noise():
    e = TransitionEngine(TransitionSettings(sensitivity=40, smoothing=0))
    base = lab4(RED, BLUE, GREEN, YELLOW)
    e.reset(base)
    rng = np.random.default_rng(0)
    for i in range(50):
        e.set_targets(base + rng.normal(0, 0.004, base.shape).astype(np.float32), i * 0.05)
    assert np.allclose(e.target, base)


def test_smoothing_stability():
    e = TransitionEngine(TransitionSettings(smoothing=90, sensitivity=100))
    base = lab4(RED, BLUE, GREEN, YELLOW)
    e.reset(base)
    noisy = base.copy()
    noisy[0] = lab4(GREEN)[0]  # one-frame outlier
    e.set_targets(noisy, 0.0)
    e.set_targets(base, 0.05)
    assert float(delta_e(e.target[0], base[0])) < 0.2


def test_palette_assignment_prevents_zone_hopping():
    prev = lab4(RED, BLUE, GREEN, YELLOW)
    new = lab4(BLUE, YELLOW, RED, GREEN)  # same colours, new order
    perm = best_assignment(prev, new)
    assert np.allclose(new[list(perm)], prev)
    e = TransitionEngine(TransitionSettings(smoothing=0, sensitivity=100))
    e.reset(prev)
    e.set_targets(new, 0.0, reorderable=True)
    assert np.allclose(e.target, prev)
    e.set_targets(new, 0.1, reorderable=False)  # spatial mode keeps positions
    assert np.allclose(e.target, new)


def test_assignment_identity_when_equivalent():
    same = lab4(RED, RED, RED, RED)
    assert best_assignment(same, same) == (0, 1, 2, 3)


def test_parameter_mappings_monotonic():
    taus = [tau_for_speed(s) for s in range(0, 101, 10)]
    assert all(b < a for a, b in zip(taus, taus[1:]))
    thr = [threshold_for_sensitivity(s) for s in range(0, 101, 10)]
    assert all(b < a for a, b in zip(thr, thr[1:]))


def test_no_unnecessary_updates_deadband():
    db = OutputDeadband(min_diff=3)
    a = ((100, 0, 0),) * 4
    assert db.filter(a, converged=False) == a
    assert db.filter(((101, 0, 0),) * 4, converged=False) is None
    assert db.filter(((104, 0, 0),) * 4, converged=False) is not None
    final = ((105, 0, 0),) * 4
    assert db.filter(final, converged=True) == final  # final value always lands
    assert db.filter(final, converged=True) is None  # but only once


def test_engine_stops_submitting_when_converged():
    e = TransitionEngine(TransitionSettings(transition_speed=80))
    e.reset(lab4(RED, RED, RED, RED))
    e.set_targets(lab4(BLUE, BLUE, BLUE, BLUE), 0.0, cut=True)
    db = OutputDeadband(2)
    sent = 0
    t = 0.0
    for _ in range(120):
        t += 1 / 30
        cur = e.step(t)
        if db.filter(finalize(cur, OutputSettings(saturation=100)), e.converged()) is not None:
            sent += 1
    assert e.converged()
    assert 0 < sent < 40


def test_output_stage_brightness_and_saturation():
    lab = lab4(RED, BLUE, GREEN, YELLOW)
    full = finalize(lab, OutputSettings(brightness=100, saturation=100))
    assert full[0] == (255, 0, 0)
    half = finalize(lab, OutputSettings(brightness=50, saturation=100))
    assert half[0] == (128, 0, 0)
    grey = finalize(lab, OutputSettings(saturation=0))
    assert abs(grey[0][0] - grey[0][1]) <= 2
    assert scale_zone_colors(full, 0.5)[1] == (0, 0, 128)
