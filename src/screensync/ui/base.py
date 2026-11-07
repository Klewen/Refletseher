"""Shared UI context, page base class and status text helpers."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core.controller import AppController, AppSnapshot, Mode
from ..device.worker import ConnectionState, DeviceSnapshot
from ..effects import EffectId
from ..i18n import tr
from .widgets.common import label


class UiContext(QObject):
    profilesChanged = Signal()
    settingsChanged = Signal()
    navigate = Signal(str, object)  # page key, argument
    notify = Signal(str, str)  # message, level

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller

    @property
    def settings(self):
        return self.controller.settings

    def save_settings(self, **changes) -> None:
        self.controller.settings_store.update(**changes)
        self.settingsChanged.emit()


class Page(QWidget):
    key = "page"

    def __init__(self, ctx: UiContext, title: str, subtitle: str = "", scroll: bool = True) -> None:
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 18)
        outer.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_label = label(title, "PageTitle")
        col.addWidget(self.title_label)
        if subtitle:
            col.addWidget(label(subtitle, "PageSubtitle"))
        head.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        outer.addLayout(head)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = QWidget()
            self.content = QVBoxLayout(inner)
            self.content.setContentsMargins(0, 0, 6, 0)
            self.content.setSpacing(16)
            area.setWidget(inner)
            outer.addWidget(area, 1)
        else:
            self.content = QVBoxLayout()
            self.content.setSpacing(16)
            outer.addLayout(self.content, 1)

    @property
    def controller(self) -> AppController:
        return self.ctx.controller

    def update_snapshot(self, snap: AppSnapshot) -> None:  # pragma: no cover - overridden
        pass

    def on_shown(self) -> None:
        pass


# ------------------------------------------------------------------ texts
def device_status(dev: DeviceSnapshot, simulation: bool) -> tuple[str, str]:
    st = dev.state
    if st == ConnectionState.CONNECTED:
        text, level = tr("device.connected"), "success"
        if dev.stalled:
            text, level = tr("device.stalled"), "warning"
    elif st == ConnectionState.CONNECTING:
        text, level = tr("device.connecting"), "info"
    elif st == ConnectionState.NOT_FOUND:
        text, level = tr("device.not_found"), "danger"
    elif st == ConnectionState.ACCESS_DENIED:
        text, level = tr("device.access_denied"), "danger"
    elif st == ConnectionState.ERROR:
        text, level = tr("device.error"), "warning"
    elif st == ConnectionState.SUSPENDED:
        text, level = tr("device.suspended"), "muted"
    else:
        text, level = tr("device.stopped"), "muted"
    if simulation:
        text = f"{text} · {tr('device.simulation')}"
        level = "accent" if level == "success" else level
    return text, level


def keyboard_badge(snap: AppSnapshot) -> tuple[str, str]:
    if snap.simulation_backend:
        return tr("badge.simulation_backend"), "accent"
    dev = snap.device
    if snap.simulated:
        if dev.connected and not dev.pending:
            return tr("badge.hw_effect_sent"), "info"
        return tr("badge.hw_effect_pending"), "warning"
    if not dev.connected:
        return tr("badge.not_sent"), "warning"
    if dev.pending:
        return tr("badge.sending"), "info"
    return tr("badge.sent"), "success"


def mode_text(snap: AppSnapshot) -> str:
    if snap.mode == Mode.OFF:
        return tr("mode.off")
    if snap.mode == Mode.STATIC:
        return tr("mode.static")
    if snap.mode == Mode.EFFECT:
        name = effect_name(snap.effect.effect)
        kind = tr("effects.hardware") if snap.hardware_effect is not None else tr("effects.software")
        return f"{tr('mode.effect')}: {name} ({kind})"
    if snap.mode == Mode.SCREEN_SYNC:
        algo = snap.sync.mode_label if snap.sync and snap.sync.mode_label else ""
        return f"{tr('mode.screen_sync')}" + (f" · {algo_name(algo)}" if algo else "")
    return snap.mode.value


def effect_name(eid: EffectId) -> str:
    return tr(f"effect.{eid.value}")


def algo_name(key: str) -> str:
    return tr(f"algo.{key}") if key else ""


def fmt_age(ts: float | None) -> str:
    if ts is None:
        return tr("common.never")
    age = time.time() - ts
    if age < 2:
        return tr("common.just_now")
    if age < 60:
        return tr("common.seconds_ago", n=int(age))
    if age < 3600:
        return tr("common.minutes_ago", n=int(age // 60))
    return time.strftime("%H:%M:%S", time.localtime(ts))
