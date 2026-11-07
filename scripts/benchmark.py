"""ScreenSync RGB benchmark.

    uv run python scripts/benchmark.py                       # synthetic + real capture, mock HID
    uv run python scripts/benchmark.py --animate             # show a moving colour window so DXGI gets frames
    uv run python scripts/benchmark.py --animate --hardware  # + real MS-1565 writes (allow-listed commands only)

Measures: capture latency per backend, colour extraction latency per mode,
transition processing latency, HID update latency, effective RGB
updates/s, CPU utilisation, memory, dropped frames and skipped HID writes.
Writes benchmarks/results-<timestamp>.json and prints a Markdown summary.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import psutil  # noqa: E402

from screensync.capture import CaptureError, CaptureUnavailable, Region, create_backend  # noqa: E402
from screensync.capture import synthetic as S  # noqa: E402
from screensync.capture.monitors import enumerate_monitors, find_monitor  # noqa: E402
from screensync.color.extractors import ColorAnalyzer  # noqa: E402
from screensync.color.frame import compute_features  # noqa: E402
from screensync.color.settings import AnalysisSettings, OutputSettings, SyncMode, TransitionSettings  # noqa: E402
from screensync.core.settings import PERFORMANCE_PRESETS  # noqa: E402
from screensync.device.mock import MockBackend  # noqa: E402
from screensync.device.transport import HidapiBackend  # noqa: E402
from screensync.device.worker import DeviceWorker, WorkerConfig  # noqa: E402
from screensync.sync.engine import ScreenSyncEngine, SyncConfig  # noqa: E402
from screensync.sync.output import finalize  # noqa: E402
from screensync.sync.transition import TransitionEngine  # noqa: E402


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "median_ms": round(statistics.median(values), 3) if values else None,
        "p95_ms": round(pct(values, 0.95), 3) if values else None,
        "max_ms": round(max(values), 3) if values else None,
    }


# --------------------------------------------------------------- sections
def bench_color(iterations: int = 150) -> dict:
    scenes = {
        "film": S.blobs((200, 230, 250), [((210, 30, 40), 0.2, 0.7, 0.25), ((235, 225, 200), 0.75, 0.6, 0.35), ((110, 20, 40), 0.5, 0.9, 0.12)]),
        "moving": S.moving_scene(4.2),
        "dark_accent": S.blobs((4, 4, 6), [((255, 30, 20), 0.7, 0.4, 0.08)]),
        "noise": np.random.default_rng(0).integers(0, 256, (90, 160, 3)).astype(np.uint8),
    }
    out = {}
    for mode in SyncMode:
        analyzer = ColorAnalyzer(AnalysisSettings(mode=mode))
        times = []
        for i in range(iterations):
            img = list(scenes.values())[i % len(scenes)]
            t0 = time.perf_counter()
            analyzer.analyze(compute_features(img))
            times.append((time.perf_counter() - t0) * 1000)
        out[mode.value] = summary(times[10:])
    return out


def bench_transition(iterations: int = 3000) -> dict:
    eng = TransitionEngine(TransitionSettings())
    rng = np.random.default_rng(1)
    eng.set_targets(rng.random((4, 3)).astype(np.float32) * 0.5, 0.0)
    times = []
    t = 0.0
    for i in range(iterations):
        t += 1 / 30
        if i % 3 == 0:
            eng.set_targets(rng.random((4, 3)).astype(np.float32) * 0.5, t)
        t0 = time.perf_counter()
        cur = eng.step(t)
        finalize(cur, OutputSettings())
        times.append((time.perf_counter() - t0) * 1000)
    return summary(times)


def bench_capture(seconds: float = 3.0) -> dict:
    mons = enumerate_monitors()
    mon = find_monitor(mons, None)
    out: dict = {"monitor": mon.label if mon else None, "hdr": bool(mon and mon.hdr_enabled)}
    if mon is None:
        return out
    for name in ("dxgi", "winrt", "gdi"):
        try:
            cap = create_backend(name)
            cap.open(mon, Region())
        except (CaptureUnavailable, CaptureError) as exc:
            out[name] = {"error": str(exc)}
            continue
        times, none = [], 0
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            t0 = time.perf_counter()
            try:
                f = cap.grab()
            except CaptureError as exc:
                out[name] = {"error": str(exc)}
                break
            dt = (time.perf_counter() - t0) * 1000
            if f is None:
                none += 1
            else:
                times.append(dt)
            time.sleep(1 / 30)
        cap.close()
        out.setdefault(name, {})
        out[name].update({"frames": len(times), "no_new_frame": none, **summary(times)})
    return out


class Animator:
    """Borderless window with slowly drifting colours (no flashing) so that
    DXGI delivers new frames during the benchmark."""

    def __init__(self) -> None:
        self.thread_ready = threading.Event()

    def run(self, seconds: float) -> None:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QApplication, QWidget

        app = QApplication.instance() or QApplication([])

        class W(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.t0 = time.monotonic()
                self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
                scr = app.primaryScreen().geometry()
                self.setGeometry(scr.x(), scr.y(), scr.width(), scr.height())

            def paintEvent(self, _e) -> None:  # noqa: N802
                t = time.monotonic() - self.t0
                p = QPainter(self)
                w = self.width()
                for i in range(4):
                    hue = (t * 25 + i * 80) % 360
                    p.fillRect(int(i * w / 4), 0, int(w / 4) + 1, self.height(), QColor.fromHsvF(hue / 360, 0.85, 0.9))

        win = W()
        win.show()
        timer = QTimer()
        timer.timeout.connect(win.update)
        timer.start(16)
        QTimer.singleShot(int(seconds * 1000), app.quit)
        app.exec()
        win.close()


def bench_pipeline(seconds: float, hardware: bool, performance: str, synthetic: bool) -> dict:
    backend = HidapiBackend() if hardware else MockBackend()
    preset = PERFORMANCE_PRESETS[performance]
    worker = DeviceWorker(lambda: backend, WorkerConfig(update_hz=preset["update_hz"]))
    worker.start()
    submitted = [0]

    def sink(colors):
        submitted[0] += 1
        worker.submit_colors(colors, "bench")

    if synthetic:
        synth = S.SyntheticBackend(S.moving_scene)
        engine = ScreenSyncEngine(sink, monitors_fn=lambda: [S.SYNTHETIC_MONITOR], backend_factory=lambda n: synth)
    else:
        engine = ScreenSyncEngine(sink)
    proc = psutil.Process()
    proc.cpu_percent(None)
    mem0 = proc.memory_info().rss
    engine.start(SyncConfig(analysis=AnalysisSettings(mode=SyncMode.PALETTE), analysis_fps=preset["analysis_fps"], output_hz=preset["output_hz"]))
    cpu_samples, mem_samples = [], []
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        time.sleep(0.5)
        cpu_samples.append(proc.cpu_percent(None) / psutil.cpu_count())
        mem_samples.append(proc.memory_info().rss / 2**20)
    st = engine.snapshot()
    engine.stop()
    worker.wait_idle(1.0)
    d = worker.snapshot()
    lat = worker.frame_latencies()
    worker.stop()
    return {
        "hid": "hidapi (real MS-1565)" if hardware else "mock",
        "capture": "synthetic" if synthetic else st.backend,
        "performance": performance,
        "seconds": seconds,
        "capture_fps": round(st.capture_fps, 2),
        "analysis_fps": round(st.analysis_fps, 2),
        "capture_ms": round(st.capture_ms, 2),
        "analysis_ms": round(st.analysis_ms, 2),
        "transition_ms": round(st.transition_ms, 3),
        "pipeline_ms": round(st.pipeline_ms, 2),
        "engine_thread_cpu_pct_of_one_core": round(st.cpu_percent, 2),
        "process_cpu_pct_total_median": round(statistics.median(cpu_samples), 2) if cpu_samples else None,
        "process_rss_mb_max": round(max(mem_samples), 1) if mem_samples else None,
        "process_rss_mb_delta": round((max(mem_samples) * 2**20 - mem0) / 2**20, 1) if mem_samples else None,
        "frames_captured": st.frames_captured,
        "frames_analyzed": st.frames_analyzed,
        "frames_no_change": st.frames_no_change,
        "frames_static_skipped": st.frames_static,
        "dropped_ticks": st.frames_dropped,
        "engine_submissions": submitted[0],
        "deadband_suppressed": st.deadband_suppressed,
        "hid_frames_applied": d.frames_applied,
        "hid_duplicates_skipped": d.duplicates_skipped,
        "hid_frames_coalesced": d.frames_coalesced,
        "hid_packets": d.packets_sent,
        "hid_effective_updates_per_s": round(d.frames_applied / seconds, 2),
        "hid_write_latency_ms_last": round(d.write_latency_ms, 3),
        "hid_submit_to_write_latency": summary(lat),
        "hid_errors": d.error_count,
        "hid_ack_failures": d.ack_failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hardware", action="store_true", help="write to the real keyboard (allow-listed commands only)")
    ap.add_argument("--animate", action="store_true", help="show a moving colour window during the live pipeline test")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out", type=Path, default=Path("benchmarks"))
    ap.add_argument("--animator-only", type=float, default=0.0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.animator_only:
        Animator().run(args.animator_only)
        return 0
    results: dict = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "machine": {"cpu_count": psutil.cpu_count(), "cpu": os.environ.get("PROCESSOR_IDENTIFIER", ""), "python": sys.version.split()[0]},
    }
    print("colour extraction ...", flush=True)
    results["color_extraction_ms"] = bench_color()
    print("transition ...", flush=True)
    results["transition_step_ms"] = bench_transition()
    print("capture backends ...", flush=True)
    results["capture"] = bench_capture()
    print("pipeline (synthetic frames, mock HID) ...", flush=True)
    results["pipeline_synthetic_mock"] = {p: bench_pipeline(min(args.seconds, 6), False, p, True) for p in ("eco", "balanced", "responsive")}

    live_result: dict = {}

    def live() -> None:
        time.sleep(1.0)
        print("pipeline (live screen) ...", flush=True)
        live_result["balanced"] = bench_pipeline(args.seconds, args.hardware, "balanced", False)

    if args.animate:
        # separate process: the animation must not compete for our GIL/CPU
        import subprocess

        anim = subprocess.Popen([sys.executable, __file__, "--animator-only", str(args.seconds + 2.5)])
        live()
        anim.wait(timeout=30)
    else:
        live()
    results["pipeline_live"] = live_result
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"results-{time.strftime('%Y%m%d-%H%M%S')}{'-hw' if args.hardware else ''}.json"
    path.write_text(json.dumps(results, indent=2), "utf-8")
    print(json.dumps(results, indent=2))
    print("saved", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
