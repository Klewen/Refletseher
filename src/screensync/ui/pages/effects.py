"""Effects Studio: choose, tune, preview and run lighting effects."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from ...core.controller import AppSnapshot, Mode
from ...effects import SPECS, EffectConfig, EffectId, render, to_hardware
from ...i18n import tr
from ...rgb import RGB
from ..base import Page, UiContext, effect_name
from ..widgets.color_picker import ColorPicker
from ..widgets.common import Card, Segmented, SliderRow, StatusPill, Swatch, ToggleRow, button, label
from ..widgets.keyboard_view import KeyboardView


def pick_color(parent, color: RGB) -> RGB | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("effects.pick_color"))
    lay = QVBoxLayout(dlg)
    picker = ColorPicker(color)
    lay.addWidget(picker)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    dlg.resize(380, 420)
    return picker.color() if dlg.exec() == QDialog.DialogCode.Accepted else None


class EffectsPage(Page):
    key = "effects"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("effects.title"), tr("effects.subtitle"))
        self._cfg = EffectConfig.from_dict(self.controller.state.effect.to_dict())
        self.stop_btn = button(tr("effects.stop"), on_click=self.controller.stop_effect)
        self.start_btn = button(tr("effects.start"), primary=True, on_click=self._start)
        self.actions.addWidget(self.stop_btn)
        self.actions.addWidget(self.start_btn)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        lst = Card(tr("effects.list"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.effect_buttons: dict[EffectId, QPushButton] = {}
        for i, eid in enumerate(EffectId):
            spec = SPECS[eid]
            kind = tr("effects.hw_badge") if spec.hardware else tr("effects.sw_badge")
            b = button(f"{effect_name(eid)}\n{kind}", chip=True)
            b.setMinimumHeight(52)
            b.setStyleSheet("text-align: left; padding: 8px 12px; border-radius: 10px;")
            b.clicked.connect(lambda _=False, e=eid: self._select(e))
            self.effect_buttons[eid] = b
            grid.addWidget(b, i // 2, i % 2)
        lst.add_layout(grid)
        lst.add(label(tr("effects.photosensitivity"), caption=True, wrap=True))
        lst.body.addStretch(1)
        cols.addWidget(lst, 4)

        right = QVBoxLayout()
        right.setSpacing(16)
        prev = Card(tr("effects.preview"))
        self.kind_pill = StatusPill()
        prev.header.addWidget(self.kind_pill, 0, Qt.AlignmentFlag.AlignTop)
        self.desc = label("", caption=True, wrap=True)
        prev.add(self.desc)
        self.keyboard = KeyboardView(interactive=False)
        self.keyboard.setMinimumHeight(220)
        self.keyboard.set_zone_labels([tr("zone.n", n=i + 1) for i in range(4)])
        prev.add(self.keyboard, 1)
        self.preview_note = label("", caption=True, wrap=True)
        prev.add(self.preview_note)
        right.addWidget(prev, 1)

        params = Card(tr("effects.parameters"))
        self.speed = SliderRow(tr("effects.speed"), 0, 100, 50, fmt=self._speed_fmt)
        self.speed.valueChanged.connect(self._param_changed)
        self.brightness = SliderRow(tr("effects.brightness"), 0, 100, 100, "%")
        self.brightness.valueChanged.connect(self._param_changed)
        self.direction = Segmented([("ltr", tr("effects.ltr")), ("rtl", tr("effects.rtl"))], "ltr")
        self.direction.changed.connect(self._param_changed)
        self.prefer_hw = ToggleRow(tr("effects.prefer_hw"), True, tr("effects.prefer_hw_hint"))
        self.prefer_hw.toggled.connect(self._param_changed)
        params.add(self.speed)
        params.add(self.brightness)
        self.dir_label = label(tr("effects.direction"), secondary=True)
        params.add(self.dir_label)
        params.add(self.direction)
        self.colors_label = label(tr("effects.colors"), secondary=True)
        params.add(self.colors_label)
        self.colors_row = QHBoxLayout()
        self.colors_row.setSpacing(8)
        params.add_layout(self.colors_row)
        self.colors_hint = label(tr("effects.colors_hint"), caption=True)
        params.add(self.colors_hint)
        params.add(self.prefer_hw)
        right.addWidget(params)
        cols.addLayout(right, 5)
        self.content.addLayout(cols)

        self._t0 = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick_preview)
        self._load(self._cfg)

    # ----------------------------------------------------------- helpers
    def _speed_fmt(self, v: int) -> str:
        cfg = EffectConfig.from_dict({**self._cfg.to_dict(), "speed": v}) if hasattr(self, "_cfg") else EffectConfig(speed=v)
        return f"{cfg.period():.1f} s"

    def _load(self, cfg: EffectConfig) -> None:
        self._cfg = cfg
        for eid, b in self.effect_buttons.items():
            b.setChecked(eid == cfg.effect)
        spec = cfg.spec
        for w in (self.speed, self.brightness):
            w.blockSignals(True)
        self.speed.setValue(cfg.speed)
        self.brightness.setValue(cfg.brightness)
        for w in (self.speed, self.brightness):
            w.blockSignals(False)
        self.speed.value_label.setText(self._speed_fmt(cfg.speed))
        self.direction.set_current(cfg.direction)
        self.prefer_hw.setChecked(cfg.prefer_hardware)
        self.dir_label.setVisible(spec.uses_direction)
        self.direction.setVisible(spec.uses_direction)
        self.prefer_hw.setVisible(spec.hardware and spec.software)
        self.speed.setVisible(cfg.effect != EffectId.STATIC)
        self.desc.setText(tr(f"effect.{cfg.effect.value}.desc"))
        self._rebuild_colors()
        self._update_kind()

    def _rebuild_colors(self) -> None:
        while self.colors_row.count():
            it = self.colors_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        spec = self._cfg.spec
        show = spec.uses_colors
        self.colors_label.setVisible(show)
        self.colors_hint.setVisible(show)
        if not show:
            return
        cols = self._cfg.colors or list(spec.default_colors)
        for i, c in enumerate(cols):
            sw = Swatch(c, 30)
            sw.clicked.connect(lambda _=False, idx=i: self._edit_color(idx))
            sw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            sw.customContextMenuRequested.connect(lambda _p, idx=i: self._remove_color(idx))
            self.colors_row.addWidget(sw)
        if len(cols) < spec.max_colors:
            self.colors_row.addWidget(button(icon="", tooltip=tr("effects.add_color"), on_click=self._add_color))
        self.colors_row.addStretch(1)

    def _colors(self) -> list[RGB]:
        return list(self._cfg.colors or self._cfg.spec.default_colors)

    def _edit_color(self, idx: int) -> None:
        cols = self._colors()
        c = pick_color(self, cols[idx])
        if c is not None:
            cols[idx] = c
            self._cfg.colors = cols
            self._rebuild_colors()
            self._param_changed()

    def _add_color(self) -> None:
        cols = self._colors()
        c = pick_color(self, cols[-1] if cols else (255, 255, 255))
        if c is not None:
            cols.append(c)
            self._cfg.colors = cols[: self._cfg.spec.max_colors]
            self._rebuild_colors()
            self._param_changed()

    def _remove_color(self, idx: int) -> None:
        cols = self._colors()
        if len(cols) > max(1, self._cfg.spec.min_colors):
            cols.pop(idx)
            self._cfg.colors = cols
            self._rebuild_colors()
            self._param_changed()

    def _update_kind(self) -> None:
        hw = to_hardware(self._cfg) is not None
        if self._cfg.effect == EffectId.STATIC:
            self.kind_pill.set_status(tr("effects.kind_static"), "success")
            self.preview_note.setText(tr("effects.note_static"))
        elif hw:
            self.kind_pill.set_status(tr("effects.kind_hw"), "info")
            self.preview_note.setText(tr("effects.note_hw"))
        else:
            self.kind_pill.set_status(tr("effects.kind_sw"), "accent")
            self.preview_note.setText(tr("effects.note_sw"))

    # ----------------------------------------------------------- actions
    def _select(self, eid: EffectId) -> None:
        cfg = EffectConfig(eid, speed=SPECS[eid].default_speed, brightness=self._cfg.brightness, direction=self._cfg.direction,
                           prefer_hardware=self._cfg.prefer_hardware)
        self._load(cfg)
        self._t0 = time.perf_counter()
        self._apply_if_running()

    def _param_changed(self, *_a) -> None:
        self._cfg.speed = self.speed.value()
        self._cfg.brightness = self.brightness.value()
        self._cfg.direction = self.direction.current() or "ltr"
        self._cfg.prefer_hardware = self.prefer_hw.isChecked()
        self._update_kind()
        self._apply_if_running()

    def _apply_if_running(self) -> None:
        if self.controller.state.mode == Mode.EFFECT:
            self._start()

    def _start(self) -> None:
        if self._cfg.effect == EffectId.STATIC:
            cols = self._colors()
            cols = (cols * 4)[:4]
            self.controller.set_static(zone_colors=cols)
            return
        self.controller.start_effect(self._cfg)

    def _tick_preview(self) -> None:
        self.keyboard.set_colors(render(self._cfg, time.perf_counter() - self._t0))

    def on_shown(self) -> None:
        st = self.controller.state
        if st.mode == Mode.EFFECT:
            self._load(EffectConfig.from_dict(st.effect.to_dict()))
        self._timer.start()

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def update_snapshot(self, snap: AppSnapshot) -> None:
        running = snap.mode == Mode.EFFECT
        self.stop_btn.setEnabled(running)
        self.start_btn.setText(tr("effects.update") if running else tr("effects.start"))
        if running:
            self.keyboard.set_badge(tr("effects.running"), "success")
        else:
            self.keyboard.set_badge(tr("effects.preview_only"), "muted")
