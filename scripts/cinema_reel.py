"""Film-like test reel: each scene shows what the keyboard should do.

Real HID + real screen capture, driven through the real AppController, so
the whole pipeline is exercised. The reel runs full-screen in a separate
process; this process switches algorithms per scene and logs the colours
the app intended to send. Only allow-listed commands are written.

    uv run python scripts/cinema_reel.py            # real keyboard
    uv run python scripts/cinema_reel.py --simulate
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# (seconds, algorithm, title, expectation, painter-id)
SCENES = [
    (12, "cinematic", "1/5  Karanlik sahne + kucuk kirmizi isik", "Beklenen: klavye LOS kirmizi (tamamen sonuk degil, parlak da degil)", "dark_red"),
    (8, "cinematic", "2/5  Tamamen siyah sahne", "Beklenen: klavye karanlik / sonuk", "black"),
    (12, "palette", "3/5  Film sahnesi: kirmizi cicek, acik mavi gokyuzu, krem duvar, bordo", "Beklenen: 4 bolgede bu renkler, bolge degistirmeden", "film"),
    (12, "palette", "4/5  Mavi sahne + beyaz altyazi", "Beklenen: tum bolgeler MAVI, altyazi beyazi yansimaz, titreme yok", "subtitle"),
    (12, "adaptive", "5/5  Letterbox'li (siyah seritli) turuncu/mor sahne", "Beklenen: turuncu ve mor; siyah seritler klavyeyi karartmaz", "letterbox"),
]


def run_reel() -> int:
    from PySide6.QtCore import QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication(sys.argv[:1])

    class Reel(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.t0 = time.monotonic()
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.setCursor(Qt.CursorShape.BlankCursor)

        def keyPressEvent(self, e) -> None:  # noqa: N802
            if e.key() == Qt.Key.Key_Escape:
                app.quit()

        def scene(self) -> tuple[int, float]:
            t = time.monotonic() - self.t0
            acc = 0.0
            for i, s in enumerate(SCENES):
                if t < acc + s[0]:
                    return i, t - acc
                acc += s[0]
            return len(SCENES) - 1, SCENES[-1][0]

        def paintEvent(self, _e) -> None:  # noqa: N802
            i, t = self.scene()
            _, _, title, expect, kind = SCENES[i]
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            if kind == "dark_red":
                p.fillRect(0, 0, w, h, QColor(5, 5, 8))
                p.setBrush(QColor(255, 30, 20))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(w * 0.68, h * 0.42, h * 0.10, h * 0.10))
            elif kind == "black":
                p.fillRect(0, 0, w, h, QColor(0, 0, 0))
            elif kind == "film":
                p.fillRect(0, 0, w, h, QColor(200, 230, 250))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(235, 225, 200))
                p.drawRect(QRectF(w * 0.52, h * 0.25, w * 0.48, h * 0.75))
                p.setBrush(QColor(210, 30, 40))
                for k in range(7):
                    p.drawEllipse(QRectF(w * (0.05 + 0.055 * k), h * (0.62 + 0.03 * (k % 2)), h * 0.12, h * 0.12))
                p.setBrush(QColor(110, 20, 40))
                p.drawRect(QRectF(w * 0.52, h * 0.88, w * 0.48, h * 0.12))
            elif kind == "subtitle":
                p.fillRect(0, 0, w, h, QColor(30, 60, 200))
                sub = QFont("Segoe UI", 34, QFont.Weight.DemiBold)
                p.setFont(sub)
                lines = ["Bu bir altyazi denemesidir.", "Klavye beyaza donmemeli."]
                txt = lines[int(t / 2) % 2]
                p.setPen(QColor(0, 0, 0))
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                    p.drawText(QRectF(dx, h * 0.84 + dy, w, h * 0.08), Qt.AlignmentFlag.AlignCenter, txt)
                p.setPen(QColor(255, 255, 255))
                p.drawText(QRectF(0, h * 0.84, w, h * 0.08), Qt.AlignmentFlag.AlignCenter, txt)
            elif kind == "letterbox":
                p.fillRect(0, 0, w, h, QColor(0, 0, 0))
                bar = int(h * 0.13)
                p.fillRect(0, bar, w // 2, h - 2 * bar, QColor(255, 120, 20))
                p.fillRect(w // 2, bar, w - w // 2, h - 2 * bar, QColor(130, 30, 200))
            p.setPen(QColor(255, 255, 255) if kind != "film" else QColor(20, 20, 30))
            p.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
            p.drawText(QRectF(30, 20, w - 60, 40), Qt.AlignmentFlag.AlignLeft, f"{title}   ({SCENES[i][0] - t:.0f} s)")
            p.setFont(QFont("Segoe UI", 15))
            p.drawText(QRectF(30, 60, w - 60, 40), Qt.AlignmentFlag.AlignLeft, expect)

    r = Reel()
    r.showFullScreen()
    app.processEvents()
    r.t0 = time.monotonic()
    print("READY", flush=True)  # the controller aligns its scene schedule to this
    timer = QTimer()
    timer.timeout.connect(r.update)
    timer.start(50)
    QTimer.singleShot(int(sum(s[0] for s in SCENES) * 1000) + 500, app.quit)
    app.exec()
    return 0


def run_controller(simulate: bool) -> int:
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ["REFLETSEHER_HOME"] = tempfile.mkdtemp(prefix="refletseher-reel-")
    from refletseher.color.settings import SyncMode
    from refletseher.core.controller import AppController
    from refletseher.core.settings import SettingsStore
    from refletseher.device.mock import MockBackend
    from refletseher.paths import profiles_file, settings_file
    from refletseher.profiles.model import SyncProfile
    from refletseher.profiles.store import ProfileStore

    shared = MockBackend()
    ctrl = AppController(SettingsStore(settings_file()), ProfileStore(profiles_file()),
                         backend_factory=(lambda: shared) if simulate else None, simulated=simulate)
    # the scene captions live in the top 12 % of the screen: exclude them from
    # capture so the text itself cannot influence the colours under test
    ctrl.settings_store.update(region=[0.0, 0.12, 1.0, 0.88])
    ctrl.start(apply_startup_profile=False)
    reel = subprocess.Popen([sys.executable, __file__, "--reel-only"], stdout=subprocess.PIPE, text=True)
    while reel.stdout and reel.stdout.readline().strip() != "READY":
        if reel.poll() is not None:
            raise SystemExit("reel window failed to start")
    log: list[dict] = []
    t_start = time.monotonic()
    for seconds, algo, title, expect, _kind in SCENES:
        sp = SyncProfile()
        sp.analysis.mode = SyncMode(algo)
        ctrl.start_sync(sp) if ctrl.state.mode.value != "screen_sync" else ctrl.update_sync(sp)
        scene_start = time.monotonic()
        end = scene_start + seconds
        samples = []
        while time.monotonic() < end:
            time.sleep(0.5)
            snap = ctrl.snapshot()
            samples.append({"t": round(time.monotonic() - t_start, 1), "rel": round(time.monotonic() - scene_start, 2),
                            "intended": snap.intended, "label": snap.sync.mode_label if snap.sync else "",
                            "confirmed": snap.device.confirmed_zone_colors})
        # report the middle of the scene, never a transition edge
        last = min(samples, key=lambda x: abs(x["rel"] - 0.7 * seconds)) if samples else {}
        log.append({"scene": title, "algo": algo, "expect": expect, "final": last, "samples": samples,
                    "device_errors": ctrl.snapshot().device.error_count})
        print(f"{title}\n   algo={algo} label={last.get('label')} intended={last.get('intended')}", flush=True)
    reel.wait(timeout=30)
    ctrl.shutdown()
    out = ROOT / "benchmarks" / "cinema_reel_result.json"
    out.write_text(json.dumps(log, indent=2, default=str), "utf-8")
    print("saved", out)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--reel-only", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.reel_only:
        return run_reel()
    return run_controller(args.simulate)


if __name__ == "__main__":
    raise SystemExit(main())
