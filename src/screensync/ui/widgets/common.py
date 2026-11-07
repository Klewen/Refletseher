"""Reusable building blocks: cards, slider rows, swatches, toggles, pills."""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...rgb import RGB, to_hex
from ..theme import Glyph, icon_font_family, tokens


def label(text: str = "", obj: str | None = None, *, caption: bool = False, secondary: bool = False, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if caption:
        lb.setProperty("caption", True)
    if secondary:
        lb.setProperty("secondary", True)
    lb.setWordWrap(wrap)
    return lb


def button(text: str = "", *, primary: bool = False, ghost: bool = False, danger: bool = False,
           icon: str | None = None, tooltip: str = "", on_click: Callable | None = None, chip: bool = False) -> QPushButton:
    # Icon-only buttons use the Segoe Fluent Icons glyph font; buttons with a
    # text label stay text-only (mixed fonts in one QPushButton look poor).
    b = QPushButton(text or icon or "")
    if icon and not text:
        b.setProperty("icon", True)
    for prop, val in (("primary", primary), ("ghost", ghost), ("danger", danger), ("chip", chip)):
        if val:
            b.setProperty(prop, True)
    if chip:
        b.setCheckable(True)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


def glyph_label(glyph: str, size: int = 16, color: str | None = None) -> QLabel:
    lb = QLabel(glyph)
    fam = icon_font_family()
    lb.setStyleSheet(f'font-family: "{fam}"; font-size: {size}px; color: {color or tokens().text2};')
    return lb


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None, inner: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("CardInner" if inner else "Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 18)
        self.body.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label: QLabel | None = None
        if title:
            col = QVBoxLayout()
            col.setSpacing(2)
            self.title_label = label(title, "SectionTitle")
            col.addWidget(self.title_label)
            if subtitle:
                col.addWidget(label(subtitle, caption=True, wrap=True))
            self.header.addLayout(col, 1)
            self.body.addLayout(self.header)

    def add(self, w: QWidget | None = None, stretch: int = 0) -> None:
        if w is not None:
            self.body.addWidget(w, stretch)

    def add_layout(self, lay) -> None:
        self.body.addLayout(lay)


class SliderRow(QWidget):
    """Label - slider - value, emits ``valueChanged(int)``."""

    valueChanged = Signal(int)
    released = Signal(int)

    def __init__(self, text: str, lo: int, hi: int, value: int, suffix: str = "", fmt: Callable[[int], str] | None = None,
                 tooltip: str = "") -> None:
        super().__init__()
        self._fmt = fmt or (lambda v: f"{v}{suffix}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        self.title = label(text, secondary=True)
        self.value_label = label(self._fmt(value))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.title, 1)
        top.addWidget(self.value_label)
        lay.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(lambda: self.released.emit(self.slider.value()))
        lay.addWidget(self.slider)
        if tooltip:
            self.setToolTip(tooltip)

    def _changed(self, v: int) -> None:
        self.value_label.setText(self._fmt(v))
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int) -> None:  # noqa: N802 (Qt naming)
        if self.slider.value() != v:
            self.slider.blockSignals(True)
            self.slider.setValue(v)
            self.slider.blockSignals(False)
            self.value_label.setText(self._fmt(v))


class Swatch(QAbstractButton):
    """Round colour button."""

    def __init__(self, color: RGB = (0, 0, 0), size: int = 26, tooltip: str = "") -> None:
        super().__init__()
        self._color = QColor(*color)
        self._size = size
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        self.setToolTip(tooltip or to_hex(color))

    def color(self) -> RGB:
        return (self._color.red(), self._color.green(), self._color.blue())

    def set_color(self, color: RGB) -> None:
        self._color = QColor(*color)
        self.setToolTip(to_hex(color))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._size, self._size)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setBrush(self._color)
        ring = QColor(tokens().accent) if self.isChecked() else QColor(255, 255, 255, 40 if not self.underMouse() else 110)
        p.setPen(QPen(ring, 2 if self.isChecked() else 1))
        p.drawEllipse(r)


class ColorChip(QWidget):
    """Rounded rectangle colour preview with optional caption below."""

    def __init__(self, color: RGB | None = None, caption: str = "", height: int = 34) -> None:
        super().__init__()
        self._color = color
        self._dim = False
        self._caption = caption
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_color(self, color: RGB | None, dim: bool = False) -> None:
        if color != self._color or dim != self._dim:
            self._color, self._dim = color, dim
            self.setToolTip(to_hex(color) if color else "—")
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        t = tokens()
        if self._color is None:
            p.setPen(QPen(QColor(t.border), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor(t.muted))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "—")
            return
        c = QColor(*self._color)
        if self._dim:
            c.setAlpha(110)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(c)
        p.drawRoundedRect(r, 8, 8)


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        self.setFixedSize(40, 22)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setChecked(self, on: bool) -> None:  # noqa: N802
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, 22)

    def paintEvent(self, _e) -> None:  # noqa: N802
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on_c, off_c = QColor(t.accent), QColor(t.border)
        bg = QColor(
            int(off_c.red() + (on_c.red() - off_c.red()) * self._pos),
            int(off_c.green() + (on_c.green() - off_c.green()) * self._pos),
            int(off_c.blue() + (on_c.blue() - off_c.blue()) * self._pos),
        )
        if not self.isEnabled():
            bg.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class ToggleRow(QWidget):
    toggled = Signal(bool)

    def __init__(self, text: str, checked: bool = False, hint: str = "") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(text))
        if hint:
            col.addWidget(label(hint, caption=True, wrap=True))
        lay.addLayout(col, 1)
        self.switch = ToggleSwitch(checked)
        self.switch.toggled.connect(self.toggled.emit)
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def isChecked(self) -> bool:  # noqa: N802
        return self.switch.isChecked()

    def setChecked(self, v: bool) -> None:  # noqa: N802
        self.switch.blockSignals(True)
        self.switch.setChecked(v)
        self.switch.blockSignals(False)


class FormRow(QWidget):
    """Label (+hint) on the left, any control on the right."""

    def __init__(self, text: str, control: QWidget, hint: str = "") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(text))
        if hint:
            col.addWidget(label(hint, caption=True, wrap=True))
        lay.addLayout(col, 1)
        control.setMinimumWidth(max(control.minimumWidth(), 200))
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control


class StatusPill(QWidget):
    """Coloured dot + text."""

    def __init__(self, text: str = "", level: str = "muted") -> None:
        super().__init__()
        self._text, self._level = text, level
        self.setMinimumHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_status(self, text: str, level: str) -> None:
        if (text, level) != (self._text, self._level):
            self._text, self._level = text, level
            self.updateGeometry()
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self._text) + 34, 26)

    def paintEvent(self, _e) -> None:  # noqa: N802
        t = tokens()
        color = {"success": t.success, "warning": t.warning, "danger": t.danger, "info": t.info, "accent": t.accent}.get(self._level, t.muted)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QColor(color)
        bg.setAlpha(28)
        p.setPen(QPen(QColor(color).darker(140) if t.name == "dark" else QColor(color), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(r.left() + 10, r.center().y() - 3.5, 7, 7))
        p.setPen(QColor(t.text))
        p.drawText(r.adjusted(24, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


class Segmented(QWidget):
    """Row of exclusive chip buttons; emits ``changed(key)``."""

    changed = Signal(str)

    def __init__(self, items: Sequence[tuple[str, str]], current: str | None = None) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in items:
            b = button(text, chip=True)
            b.setProperty("key", key)
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        lay.addStretch(1)
        if current in self._buttons:
            self._buttons[current].setChecked(True)

    def set_current(self, key: str) -> None:
        b = self._buttons.get(key)
        if b and not b.isChecked():
            b.setChecked(True)

    def current(self) -> str | None:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return None


class Banner(QFrame):
    def __init__(self, level: str = "warning") -> None:
        super().__init__()
        self.setObjectName("Banner")
        self.setProperty("level", level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        t = tokens()
        color = {"warning": t.warning, "danger": t.danger, "info": t.info}.get(level, t.info)
        self.icon = glyph_label(Glyph.WARNING if level != "info" else Glyph.INFO, 16, color)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        self.text = label("", wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(False)
        lay.addWidget(self.text, 1)
        self.action: QPushButton | None = None
        self.hide()

    def set_level(self, level: str) -> None:
        self.setProperty("level", level)
        t = tokens()
        color = {"warning": t.warning, "danger": t.danger, "info": t.info}.get(level, t.info)
        self.icon.setText(Glyph.WARNING if level != "info" else Glyph.INFO)
        self.icon.setStyleSheet(f'font-family: "{icon_font_family()}"; font-size: 16px; color: {color};')
        self.style().unpolish(self)
        self.style().polish(self)

    def show_message(self, text: str, level: str | None = None) -> None:
        if level:
            self.set_level(level)
        if self.text.text() != text:
            self.text.setText(text)
        self.setVisible(bool(text))


class MetricTile(QWidget):
    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.value = label(value, "Metric")
        self.title = label(title, "MetricLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.title)

    def set_value(self, text: str) -> None:
        if self.value.text() != text:
            self.value.setText(text)


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {tokens().border}; background: {tokens().border}; max-height: 1px; border: none;")
    return f
