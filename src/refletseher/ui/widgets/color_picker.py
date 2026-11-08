"""HSV colour picker: saturation/value square, hue strip, HEX/RGB/HSV fields."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from ...i18n import tr
from ...rgb import RGB, from_hex, hsv_to_rgb, rgb_to_hsv, to_hex
from .common import ColorChip, label


class _SVSquare(QWidget):
    changed = Signal(float, float)  # s, v
    released = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.h, self.s, self.v = 0.0, 1.0, 1.0
        self._cache: QImage | None = None
        self._cache_h = -1.0
        self.setMinimumSize(200, 150)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hsv(self, h: float, s: float, v: float) -> None:
        self.h, self.s, self.v = h, s, v
        self.update()

    def _pick(self, pos: QPointF) -> None:
        r = self.rect().adjusted(1, 1, -1, -1)
        s = min(max((pos.x() - r.left()) / max(1, r.width()), 0.0), 1.0)
        v = 1.0 - min(max((pos.y() - r.top()) / max(1, r.height()), 0.0), 1.0)
        self.s, self.v = s, v
        self.update()
        self.changed.emit(s, v)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._pick(e.position())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self.released.emit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hue = QColor.fromHsvF((self.h % 360) / 360.0, 1.0, 1.0)
        g1 = QLinearGradient(r.topLeft(), r.topRight())
        g1.setColorAt(0, QColor(255, 255, 255))
        g1.setColorAt(1, hue)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g1)
        p.drawRoundedRect(r, 10, 10)
        g2 = QLinearGradient(r.topLeft(), r.bottomLeft())
        g2.setColorAt(0, QColor(0, 0, 0, 0))
        g2.setColorAt(1, QColor(0, 0, 0, 255))
        p.setBrush(g2)
        p.drawRoundedRect(r, 10, 10)
        x = r.left() + self.s * r.width()
        y = r.top() + (1 - self.v) * r.height()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawEllipse(QPointF(x, y), 7, 7)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(QPointF(x, y), 7, 7)


class _HueStrip(QWidget):
    changed = Signal(float)
    released = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.h = 0.0
        self.setFixedHeight(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_hue(self, h: float) -> None:
        self.h = h
        self.update()

    def _pick(self, x: float) -> None:
        w = max(1, self.width() - 2)
        self.h = min(max((x - 1) / w, 0.0), 0.9999) * 360.0
        self.update()
        self.changed.emit(self.h)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._pick(e.position().x())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position().x())

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self.released.emit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        g = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(7):
            g.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0 if i < 6 else 0.0, 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = r.left() + self.h / 360.0 * r.width()
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(QColor.fromHsvF(self.h / 360.0, 1, 1))
        p.drawEllipse(QPointF(x, r.center().y()), 7, 7)


def _spin(lo: int, hi: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    s.setAlignment(Qt.AlignmentFlag.AlignCenter)
    s.setMinimumWidth(54)
    s.setKeyboardTracking(False)
    return s


class ColorPicker(QWidget):
    """Emits ``colorChanged(r, g, b)`` live and ``colorCommitted`` on release/enter."""

    colorChanged = Signal(int, int, int)
    colorCommitted = Signal(int, int, int)

    def __init__(self, color: RGB = (255, 0, 40)) -> None:
        super().__init__()
        self._h, self._s, self._v = rgb_to_hsv(color)
        self._rgb = color
        self._updating = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.square = _SVSquare()
        self.hue = _HueStrip()
        root.addWidget(self.square, 1)
        root.addWidget(self.hue)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.preview = ColorChip(color, height=40)
        self.preview.setFixedWidth(64)
        row.addWidget(self.preview)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.hex = QLineEdit(to_hex(color))
        self.hex.setValidator(QRegularExpressionValidator(QRegularExpression(r"#?[0-9A-Fa-f]{0,6}")))
        self.hex.setMaxLength(7)
        self.hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hex.setObjectName("Mono")
        self.r, self.g, self.b = _spin(0, 255), _spin(0, 255), _spin(0, 255)
        self.hh, self.ss, self.vv = _spin(0, 359), _spin(0, 100), _spin(0, 100)
        grid.addWidget(label("HEX", caption=True), 0, 0)
        grid.addWidget(self.hex, 1, 0)
        for i, (name, sp) in enumerate((("R", self.r), ("G", self.g), ("B", self.b)), start=1):
            grid.addWidget(label(name, caption=True), 0, i, Qt.AlignmentFlag.AlignHCenter)
            grid.addWidget(sp, 1, i)
        for i, (name, sp) in enumerate((("H", self.hh), ("S", self.ss), ("V", self.vv)), start=1):
            grid.addWidget(label(name, caption=True), 2, i, Qt.AlignmentFlag.AlignHCenter)
            grid.addWidget(sp, 3, i)
        grid.addWidget(label(tr("picker.hsv"), caption=True), 2, 0)
        row.addLayout(grid, 1)
        root.addLayout(row)

        self.square.changed.connect(self._on_sv)
        self.hue.changed.connect(self._on_hue)
        self.square.released.connect(self._commit)
        self.hue.released.connect(self._commit)
        self.hex.editingFinished.connect(self._on_hex)
        for sp in (self.r, self.g, self.b):
            sp.valueChanged.connect(self._on_rgb_fields)
        for sp in (self.hh, self.ss, self.vv):
            sp.valueChanged.connect(self._on_hsv_fields)
        self._sync_widgets()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 320)

    # ------------------------------------------------------------- public
    def color(self) -> RGB:
        return self._rgb

    def set_color(self, color: RGB, emit: bool = False) -> None:
        if tuple(color) == tuple(self._rgb) and not emit:
            return
        self._rgb = tuple(color)  # type: ignore[assignment]
        h, s, v = rgb_to_hsv(color)
        if s > 0 and v > 0:
            self._h = h
        self._s, self._v = s, v
        self._sync_widgets()
        if emit:
            self.colorChanged.emit(*self._rgb)

    # ------------------------------------------------------------ handlers
    def _from_hsv(self) -> None:
        self._rgb = hsv_to_rgb(self._h, self._s, self._v)
        self._sync_widgets()
        self.colorChanged.emit(*self._rgb)

    def _on_sv(self, s: float, v: float) -> None:
        self._s, self._v = s, v
        self._from_hsv()

    def _on_hue(self, h: float) -> None:
        self._h = h
        self._from_hsv()

    def _on_hex(self) -> None:
        try:
            c = from_hex(self.hex.text())
        except ValueError:
            self.hex.setText(to_hex(self._rgb))
            return
        self.set_color(c, emit=True)
        self._commit()

    def _on_rgb_fields(self) -> None:
        if self._updating:
            return
        self.set_color((self.r.value(), self.g.value(), self.b.value()), emit=True)
        self._commit()

    def _on_hsv_fields(self) -> None:
        if self._updating:
            return
        self._h, self._s, self._v = float(self.hh.value()), self.ss.value() / 100.0, self.vv.value() / 100.0
        self._from_hsv()
        self._commit()

    def _commit(self) -> None:
        self.colorCommitted.emit(*self._rgb)

    def _sync_widgets(self) -> None:
        self._updating = True
        try:
            self.square.set_hsv(self._h, self._s, self._v)
            self.hue.set_hue(self._h)
            self.preview.set_color(self._rgb)
            if not self.hex.hasFocus():
                self.hex.setText(to_hex(self._rgb))
            for sp, v in ((self.r, self._rgb[0]), (self.g, self._rgb[1]), (self.b, self._rgb[2]),
                          (self.hh, int(self._h) % 360), (self.ss, int(round(self._s * 100))), (self.vv, int(round(self._v * 100)))):
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
        finally:
            self._updating = False
