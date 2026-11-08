"""Refletseher brand mark, drawn in code (no binary assets needed).

"Horizon & reflection": a rising sun above the horizon whose light is
mirrored below as four bars - the screen's colour carried into the four
lighting zones. Frameless; the silhouette is the logo.

Palette (Sanzo Wada, *A Dictionary of Color Combinations*):
Naples Yellow #FAED8F, Peach Red #FF3319, Deep Slate Olive #172713,
Neutral Gray #B5D1CC. Flat colours only.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

NAPLES_YELLOW = "#FAED8F"
PEACH_RED = "#FF3319"
DEEP_SLATE_OLIVE = "#172713"
NEUTRAL_GRAY = "#B5D1CC"

SUN = PEACH_RED
CORE = NAPLES_YELLOW
BARS = (NAPLES_YELLOW, PEACH_RED, NEUTRAL_GRAY, DEEP_SLATE_OLIVE)
BAR_LENGTHS = (0.20, 0.28, 0.24, 0.16)
OFF_TONES = ("#6F7A78", "#8C9896", "#6F7A78", "#5A6462")


# Bounding box of the mark in design units (fractions of the square), used to
# scale it up so it fills the icon like other desktop/tray icons do.
_BBOX = (0.23, 0.215, 0.77, 0.80)  # x0, y0, x1, y1
FILL = 0.94  # share of the icon the mark's larger side occupies


def paint_mark(p: QPainter, s: float, state: str = "normal") -> None:
    """Draw the mark into an ``s`` x ``s`` square at the painter's origin,
    scaled to fill it (with a small optical margin)."""
    x0, y0, x1, y1 = _BBOX
    k = FILL / max(x1 - x0, y1 - y0)
    p.save()
    p.translate(s * (0.5 - (x0 + x1) / 2 * k), s * (0.5 - (y0 + y1) / 2 * k))
    p.scale(k, k)
    _paint_design(p, s, state)
    p.restore()
    if state == "sync":
        # small live dot in the free top-right corner: screen sync is running
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PEACH_RED))
        p.drawEllipse(QPointF(s * 0.885, s * 0.115), s * 0.1, s * 0.1)


def _paint_design(p: QPainter, s: float, state: str) -> None:
    off = state == "off"
    p.setPen(Qt.PenStyle.NoPen)
    horizon_y = s * 0.52
    radius = s * 0.27
    centre = QPointF(s * 0.5, horizon_y - s * 0.035)
    above = QPainterPath()
    above.addRect(QRectF(0, 0, s, centre.y()))
    disc = QPainterPath()
    disc.addEllipse(centre, radius, radius)
    p.setBrush(QColor(OFF_TONES[1] if off else SUN))
    p.drawPath(disc.intersected(above))
    core = QPainterPath()
    core.addEllipse(centre, radius * 0.52, radius * 0.52)
    p.setBrush(QColor(OFF_TONES[0] if off else CORE))
    p.drawPath(core.intersected(above))
    gap = s * 0.035
    width = (2 * radius - 3 * gap) / 4
    for i, length in enumerate(BAR_LENGTHS):
        p.setBrush(QColor(OFF_TONES[i] if off else BARS[i]))
        p.drawRoundedRect(QRectF(s * 0.5 - radius + i * (width + gap), horizon_y, width, s * length), width / 2, width / 2)


def render_icon(size: int, state: str = "normal") -> QPixmap:
    """Render at 512 px and downsample: crisp edges at every icon size."""
    big = 512
    pm = QPixmap(big, big)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_mark(p, float(big), state)
    p.end()
    if size == big:
        return pm
    return pm.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


_CACHE: dict[str, QIcon] = {}


def app_icon(state: str = "normal") -> QIcon:
    icon = _CACHE.get(state)
    if icon is None:
        icon = QIcon()
        for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            icon.addPixmap(render_icon(sz, state))
        _CACHE[state] = icon
    return icon
