"""Approximate MSI Katana 15 HX keyboard with its four lighting zones.

The colours painted here are exactly what the application *intends* to
send (or a labelled simulation for native MCU effects). A status badge
states whether those colours were confirmed written to the controller.
It never claims to know the physical LED output.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...rgb import RGB, ZoneColors
from ..theme import tokens

U = 1.0  # key unit


@dataclass(frozen=True)
class Key:
    x: float
    y: float
    w: float
    h: float
    legend: str
    zone: int


def _row(y: float, keys: list[tuple[str, float]], x0: float = 0.0, h: float = 1.0) -> list[tuple[float, float, float, float, str]]:
    out = []
    x = x0
    for legend, w in keys:
        if legend:
            out.append((x, y, w, h, legend))
        x += w
    return out


# Zone boundaries in key units (main block is 15 u wide, numpad starts at 15.4)
ZONE_EDGES = (5.0, 10.0, 15.2)


def _zone_for(x_center: float) -> int:
    if x_center < ZONE_EDGES[0]:
        return 0
    if x_center < ZONE_EDGES[1]:
        return 1
    if x_center < ZONE_EDGES[2]:
        return 2
    return 3


def build_layout() -> list[Key]:
    f = 0.62  # function row height
    rows: list[tuple[float, float, float, float, str]] = []
    rows += _row(0, [("Esc", 1)] + [(f"F{i}", 1) for i in range(1, 13)] + [("Ins", 1), ("Del", 1)], h=f)
    y = f + 0.12
    rows += _row(y, [("`", 1)] + [(str(i % 10), 1) for i in range(1, 11)] + [("-", 1), ("=", 1), ("⌫", 2)])
    y += 1
    rows += _row(y, [("Tab", 1.5)] + [(c, 1) for c in "QWERTYUIOP"] + [("[", 1), ("]", 1), ("\\", 1.5)])
    y += 1
    rows += _row(y, [("Caps", 1.75)] + [(c, 1) for c in "ASDFGHJKL"] + [(";", 1), ("'", 1), ("Enter", 2.25)])
    y += 1
    rows += _row(y, [("Shift", 2.25)] + [(c, 1) for c in "ZXCVBNM"] + [(",", 1), (".", 1), ("/", 1), ("Shift", 1.75), ("↑", 1)])
    y += 1
    rows += _row(y, [("Ctrl", 1.25), ("Fn", 1), ("⊞", 1), ("Alt", 1.25), ("", 0), (" ", 5.5), ("Alt", 1), ("Ctrl", 1), ("←", 1), ("↓", 1), ("→", 1)])
    # numpad
    nx = 15.4
    rows += _row(0, [("Home", 1), ("PgUp", 1), ("PgDn", 1), ("End", 1)], x0=nx, h=f)
    y = f + 0.12
    rows += _row(y, [("Num", 1), ("/", 1), ("*", 1), ("-", 1)], x0=nx)
    rows += _row(y + 1, [("7", 1), ("8", 1), ("9", 1)], x0=nx)
    rows += [(nx + 3, y + 1, 1, 2, "+")]
    rows += _row(y + 2, [("4", 1), ("5", 1), ("6", 1)], x0=nx)
    rows += _row(y + 3, [("1", 1), ("2", 1), ("3", 1)], x0=nx)
    rows += [(nx + 3, y + 3, 1, 2, "⏎")]
    rows += _row(y + 4, [("0", 2), (".", 1)], x0=nx)
    return [Key(x, yy, w, h, lg, _zone_for(x + w / 2)) for x, yy, w, h, lg in rows]


LAYOUT = build_layout()
WIDTH_U = 15.4 + 4.0
HEIGHT_U = max(k.y + k.h for k in LAYOUT)


class KeyboardView(QWidget):
    """Interactive 4-zone keyboard preview.

    Signals: ``zoneClicked(index, additive)`` when the user clicks a zone.
    """

    zoneClicked = Signal(int, bool)

    def __init__(self, interactive: bool = True, compact: bool = False) -> None:
        super().__init__()
        self._colors: list[RGB | None] = [None, None, None, None]
        self._selected: set[int] = set()
        self._hover: int | None = None
        self._interactive = interactive
        self._compact = compact
        self._badge = ""
        self._badge_level = "muted"
        self._labels = ["Zone 1", "Zone 2", "Zone 3", "Zone 4"]
        self.setMouseTracking(interactive)
        self.setMinimumHeight(150 if compact else 230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---------------------------------------------------------------- API
    def set_colors(self, colors: ZoneColors | None) -> None:
        new = list(colors) if colors else [None, None, None, None]
        if new != self._colors:
            self._colors = new
            self.update()

    def set_selected(self, zones: set[int]) -> None:
        if zones != self._selected:
            self._selected = set(zones)
            self.update()

    def selected(self) -> set[int]:
        return set(self._selected)

    def set_badge(self, text: str, level: str = "muted") -> None:
        if (text, level) != (self._badge, self._badge_level):
            self._badge, self._badge_level = text, level
            self.update()

    def set_zone_labels(self, labels: list[str]) -> None:
        self._labels = labels
        self.update()

    # ----------------------------------------------------------- geometry
    def _geom(self) -> tuple[float, float, float]:
        pad = 14 if self._compact else 22
        bottom = 0 if self._compact else 34
        top = 24 if self._compact else 30
        avail_w = self.width() - 2 * pad
        avail_h = self.height() - top - bottom - 2 * pad
        unit = max(4.0, min(avail_w / WIDTH_U, avail_h / HEIGHT_U))
        ox = (self.width() - unit * WIDTH_U) / 2
        oy = top + pad + (avail_h - unit * HEIGHT_U) / 2
        return unit, ox, oy

    def _zone_at(self, pos: QPointF) -> int | None:
        unit, ox, oy = self._geom()
        x = (pos.x() - ox) / unit
        y = (pos.y() - oy) / unit
        if -0.3 <= y <= HEIGHT_U + 0.3 and -0.3 <= x <= WIDTH_U + 0.3:
            return _zone_for(x)
        return None

    # -------------------------------------------------------------- input
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self._interactive or e.button() != Qt.MouseButton.LeftButton:
            return
        z = self._zone_at(e.position())
        if z is not None:
            additive = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
            self.zoneClicked.emit(z, additive)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._interactive:
            return
        z = self._zone_at(e.position())
        if z != self._hover:
            self._hover = z
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _e) -> None:  # noqa: N802
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        unit, ox, oy = self._geom()
        kb = QRectF(ox - unit * 0.45, oy - unit * 0.45, unit * (WIDTH_U + 0.9), unit * (HEIGHT_U + 0.9))

        # chassis
        grad = QLinearGradient(kb.topLeft(), kb.bottomLeft())
        grad.setColorAt(0, QColor(t.chassis).lighter(135))
        grad.setColorAt(1, QColor(t.chassis))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(grad)
        p.drawRoundedRect(kb, unit * 0.45, unit * 0.45)

        # zone underglow
        x_edges = [0.0, ZONE_EDGES[0], ZONE_EDGES[1], 15.0 + 0.2, WIDTH_U]
        for z in range(4):
            c = self._colors[z]
            if c is None or max(c) < 4:
                continue
            left = ox + x_edges[z] * unit
            right = ox + (x_edges[z + 1] if z < 3 else WIDTH_U) * unit
            if z == 3:
                left = ox + 15.4 * unit
            cx, cy = (left + right) / 2, oy + HEIGHT_U * unit / 2
            rad = QRadialGradient(QPointF(cx, cy), max(right - left, HEIGHT_U * unit) * 0.75)
            glow = QColor(*c)
            glow.setAlpha(95)
            rad.setColorAt(0, glow)
            glow.setAlpha(0)
            rad.setColorAt(1, glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rad)
            p.drawRect(QRectF(left - unit, oy - unit * 0.5, right - left + 2 * unit, HEIGHT_U * unit + unit))

        # keys
        font = QFont(self.font())
        font.setPixelSize(max(7, int(unit * (0.26 if not self._compact else 0.3))))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        gap = max(1.5, unit * 0.08)
        cap = QColor(t.key_cap)
        # Partial selection: dim the keys of unselected zones (no overlapping
        # outlines - MSI zones are not rectangular across key rows).
        partial = bool(self._selected) and len(self._selected) < 4
        for k in LAYOUT:
            r = QRectF(ox + k.x * unit + gap / 2, oy + k.y * unit + gap / 2, k.w * unit - gap, k.h * unit - gap)
            p.setOpacity(0.32 if partial and k.zone not in self._selected else 1.0)
            c = self._colors[k.zone]
            lit = c is not None and max(c) >= 4
            col = QColor(*c) if lit else QColor(t.muted)
            # cap
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(cap.lighter(118))
            p.drawRoundedRect(r, unit * 0.12, unit * 0.12)
            inner = r.adjusted(1, 1, -1, -1.6)
            p.setBrush(cap)
            p.drawRoundedRect(inner, unit * 0.11, unit * 0.11)
            if lit:
                rim = QColor(col)
                rim.setAlpha(150)
                p.setPen(QPen(rim, max(1.0, unit * 0.045)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), unit * 0.12, unit * 0.12)
            if not self._compact or unit >= 18:
                legend = QColor(col) if lit else QColor(t.muted)
                if lit:
                    legend = legend.lighter(115)
                p.setPen(legend)
                p.drawText(inner, Qt.AlignmentFlag.AlignCenter, k.legend)

        p.setOpacity(1.0)
        # hover: outline the keys of the hovered zone
        if self._hover is not None:
            pen = QPen(QColor(255, 255, 255, 120), 1.2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in LAYOUT:
                if k.zone == self._hover:
                    r = QRectF(ox + k.x * unit + gap / 2, oy + k.y * unit + gap / 2, k.w * unit - gap, k.h * unit - gap)
                    p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), unit * 0.13, unit * 0.13)

        if self._compact:
            self._paint_badge(p, QRectF(kb.right(), kb.top() - 24, 0, 0), right_align=True)
            return

        # zone captions
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        for z in range(4):
            keys = [k for k in LAYOUT if k.zone == z]
            x0 = min(k.x for k in keys)
            x1 = max(k.x + k.w for k in keys)
            rr = QRectF(ox + x0 * unit, kb.bottom() + 6, (x1 - x0) * unit, 18)
            c = self._colors[z]
            text = self._labels[z] + ("  " + "#{:02X}{:02X}{:02X}".format(*c) if c is not None else "  —")
            sel = z in self._selected
            p.setPen(QColor(t.accent) if sel else QColor(t.text2))
            p.drawText(rr, Qt.AlignmentFlag.AlignCenter, text)
            if sel and len(self._selected) < 4:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t.accent))
                p.drawRoundedRect(QRectF(rr.center().x() - 18, rr.bottom() + 2, 36, 3), 1.5, 1.5)
        self._paint_badge(p, QRectF(kb.right(), kb.top() - 26, 0, 0), right_align=True)

    def _paint_badge(self, p: QPainter, anchor: QRectF, right_align: bool) -> None:
        if not self._badge:
            return
        t = tokens()
        color = {"success": t.success, "warning": t.warning, "danger": t.danger, "info": t.info, "accent": t.accent}.get(
            self._badge_level, t.muted
        )
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(self._badge) + 26
        h = 20
        x = anchor.left() - w if right_align else anchor.left()
        r = QRectF(x, anchor.top(), w, h)
        bg = QColor(color)
        bg.setAlpha(30)
        p.setPen(QPen(QColor(color), 1))
        p.setBrush(bg)
        path = QPainterPath()
        path.addRoundedRect(r, h / 2, h / 2)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(r.left() + 8, r.center().y() - 3, 6, 6))
        p.setPen(QColor(t.text))
        p.drawText(r.adjusted(18, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._badge)
