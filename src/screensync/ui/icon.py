"""Programmatically drawn application icon (no binary assets needed)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap

ZONE_COLORS = ("#FF3D6E", "#A855F7", "#22D3EE", "#34D399")


def render_icon(size: int, state: str = "normal") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    bg = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(bg.topLeft(), bg.bottomRight())
    g.setColorAt(0, QColor("#1D1F29"))
    g.setColorAt(1, QColor("#0B0C10"))
    p.setPen(QPen(QColor(255, 255, 255, 30), max(1.0, s / 64)))
    p.setBrush(g)
    p.drawRoundedRect(bg, s * 0.22, s * 0.22)

    # screen bar
    scr = QRectF(s * 0.2, s * 0.18, s * 0.6, s * 0.2)
    sg = QLinearGradient(scr.topLeft(), scr.topRight())
    for i, c in enumerate(ZONE_COLORS):
        sg.setColorAt(i / 3, QColor(c))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(sg)
    p.drawRoundedRect(scr, s * 0.05, s * 0.05)

    # keyboard: 3 rows x 4 zones
    kx, ky, kw, kh = s * 0.16, s * 0.48, s * 0.68, s * 0.34
    rows, cols = 3, 8
    gap = max(1.0, s * 0.025)
    cw = (kw - gap * (cols - 1)) / cols
    ch = (kh - gap * (rows - 1)) / rows
    dim = state == "off"
    for r in range(rows):
        for c in range(cols):
            zone = c // 2
            col = QColor(ZONE_COLORS[zone])
            if dim:
                col = QColor("#3A3D48")
            if r == 2 and 2 <= c <= 5:
                continue
            p.setBrush(col)
            p.drawRoundedRect(QRectF(kx + c * (cw + gap), ky + r * (ch + gap), cw, ch), s * 0.02, s * 0.02)
    # space bar
    p.setBrush(QColor("#3A3D48") if dim else QColor("#C9CDD8"))
    p.drawRoundedRect(QRectF(kx + 2 * (cw + gap), ky + 2 * (ch + gap), 4 * cw + 3 * gap, ch), s * 0.02, s * 0.02)
    if state == "sync":
        p.setBrush(QColor("#34D399"))
        p.setPen(QPen(QColor("#0B0C10"), max(1.0, s / 32)))
        p.drawEllipse(QRectF(s * 0.68, s * 0.06, s * 0.26, s * 0.26))
    p.end()
    return pm


def app_icon(state: str = "normal") -> QIcon:
    icon = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(render_icon(sz, state))
    return icon
