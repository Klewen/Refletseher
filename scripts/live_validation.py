"""Full-screen test pattern for observing Screen Sync on the real keyboard.

    uv run python scripts/live_validation.py [--seconds 45]

Phases (no flashing; hard cuts at most every 2.5 s):
  0-15 s   four static strips  RED | GREEN | BLUE | YELLOW  (spatial mapping)
  15-30 s  slowly drifting hues                              (smooth transitions)
  30-45 s  whole-screen cuts red -> blue -> green ...        (scene-cut response)
Press Esc to stop early.
"""

from __future__ import annotations

import argparse
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

STRIPS = [QColor(230, 30, 30), QColor(30, 200, 60), QColor(40, 60, 230), QColor(240, 210, 30)]
CUTS = [QColor(220, 20, 20), QColor(20, 40, 230), QColor(20, 200, 70)]


class Pattern(QWidget):
    def __init__(self, seconds: float) -> None:
        super().__init__()
        self.seconds = seconds
        self.t0 = time.monotonic()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            QApplication.quit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        t = time.monotonic() - self.t0
        p = QPainter(self)
        w, h = self.width(), self.height()
        third = self.seconds / 3
        if t < third:
            phase = "1/3  RED | GREEN | BLUE | YELLOW"
            for i, c in enumerate(STRIPS):
                p.fillRect(int(i * w / 4), 0, int(w / 4) + 1, h, c)
        elif t < 2 * third:
            phase = "2/3  slow drift"
            for i in range(4):
                hue = ((t - third) * 12 + i * 90) % 360
                p.fillRect(int(i * w / 4), 0, int(w / 4) + 1, h, QColor.fromHsvF(hue / 360, 0.85, 0.9))
        else:
            phase = "3/3  scene cuts"
            idx = int((t - 2 * third) / 2.5) % len(CUTS)
            p.fillRect(0, 0, w, h, CUTS[idx])
        p.setPen(QColor(255, 255, 255))
        f = QFont("Segoe UI", 16)
        p.setFont(f)
        p.drawText(30, 40, f"Refletseher live validation · {phase} · {max(0, self.seconds - t):.0f}s · Esc = stop")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=45.0)
    args = ap.parse_args()
    app = QApplication(sys.argv[:1])
    w = Pattern(args.seconds)
    w.showFullScreen()
    timer = QTimer()
    timer.timeout.connect(w.update)
    timer.start(33)
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
