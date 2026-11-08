"""Settings: general, capture, hardware, performance, automation, recovery, logs."""

from __future__ import annotations

import os
import uuid

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QTimeEdit,
)

from ... import __version__
from ...core import autostart
from ...core.controller import AppSnapshot
from ...core.settings import AutomationRule
from ...i18n import SUPPORTED, tr
from ...logging_setup import MEMORY
from ...paths import data_dir, log_dir
from ...profiles.presets import GAMING_PRESET_ID, NIGHT_PRESET_ID
from ..base import Page, UiContext
from ..widgets.common import Card, FormRow, SliderRow, ToggleRow, button, label


def _combo(items: list[tuple[str, object]], current: object) -> QComboBox:
    c = QComboBox()
    for text, data in items:
        c.addItem(text, data)
    idx = c.findData(current)
    c.setCurrentIndex(max(0, idx))
    return c


class SettingsPage(Page):
    key = "settings"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("settings.title"), tr("settings.subtitle"))
        s = ctx.settings

        # ---------------------------------------------------------- general
        gen = Card(tr("settings.general"))
        self.language = _combo([(name, code) for code, name in SUPPORTED.items()], s.language)
        self.language.currentIndexChanged.connect(self._language_changed)
        gen.add(FormRow(tr("settings.language"), self.language, tr("settings.restart_hint")))
        self.theme = _combo([(tr("settings.theme_dark"), "dark"), (tr("settings.theme_light"), "light")], s.theme)
        self.theme.currentIndexChanged.connect(lambda: self._save(theme=self.theme.currentData(), _theme=True))
        gen.add(FormRow(tr("settings.theme"), self.theme))
        self.autostart = ToggleRow(tr("settings.autostart"), autostart.is_enabled(), tr("settings.autostart_hint"))
        self.autostart.toggled.connect(self._autostart_changed)
        gen.add(self.autostart)
        self.start_min = ToggleRow(tr("settings.start_minimized"), s.start_minimized)
        self.start_min.toggled.connect(lambda v: self._save(start_minimized=v))
        gen.add(self.start_min)
        self.close_tray = ToggleRow(tr("settings.close_to_tray"), s.close_to_tray)
        self.close_tray.toggled.connect(lambda v: self._save(close_to_tray=v))
        gen.add(self.close_tray)
        self.startup = QComboBox()
        self.startup.currentIndexChanged.connect(lambda: self._save(startup_profile=self.startup.currentData() or "last"))
        gen.add(FormRow(tr("settings.startup_profile"), self.startup))
        self.exit_action = _combo([(tr("settings.exit_restore"), "restore"), (tr("settings.exit_keep"), "keep"), (tr("settings.exit_off"), "off")], s.exit_action)
        self.exit_action.currentIndexChanged.connect(lambda: self._save(exit_action=self.exit_action.currentData()))
        gen.add(FormRow(tr("settings.exit_action"), self.exit_action, tr("settings.exit_action_hint")))
        self.content.addWidget(gen)

        # ---------------------------------------------------------- capture
        cap = Card(tr("settings.capture"))
        self.backend = _combo([(tr(f"backend.{k}"), k) for k in ("auto", "dxgi", "winrt", "gdi")], s.capture_backend)
        self.backend.currentIndexChanged.connect(self._backend_changed)
        cap.add(FormRow(tr("sync.backend"), self.backend, tr("settings.backend_hint")))
        self.hdr = ToggleRow(tr("settings.hdr_comp"), s.hdr_compensation, tr("settings.hdr_comp_hint"))
        self.hdr.toggled.connect(lambda v: (self._save(hdr_compensation=v), self.controller.apply_capture_settings()))
        cap.add(self.hdr)
        cap.add(label(tr("settings.privacy"), caption=True, wrap=True))
        self.content.addWidget(cap)

        # --------------------------------------------------------- hardware
        hw = Card(tr("settings.hardware"))
        self.hw_enabled = ToggleRow(tr("settings.hw_enabled"), s.hardware_enabled, tr("settings.hw_enabled_hint"))
        self.hw_enabled.toggled.connect(lambda v: (self._save(hardware_enabled=v), self.controller.apply_device_settings()))
        hw.add(self.hw_enabled)
        self.rate = SliderRow(tr("sync.update_rate"), 1, 15, int(s.update_hz), " Hz", tooltip=tr("sync.update_rate_hint"))
        self.rate.released.connect(lambda v: (self._save(update_hz=float(v)), self.controller.apply_device_settings()))
        hw.add(self.rate)
        hw.add(label(tr("settings.rate_hint"), caption=True, wrap=True))
        self.ack = ToggleRow(tr("settings.ack_read"), s.ack_read, tr("settings.ack_read_hint"))
        self.ack.toggled.connect(lambda v: (self._save(ack_read=v), self.controller.apply_device_settings()))
        hw.add(self.ack)
        self.refresh = QDoubleSpinBox()
        self.refresh.setRange(0, 600)
        self.refresh.setDecimals(0)
        self.refresh.setSuffix(" s")
        self.refresh.setValue(s.refresh_interval_s)
        self.refresh.setKeyboardTracking(False)
        self.refresh.valueChanged.connect(lambda v: (self._save(refresh_interval_s=float(v)), self.controller.apply_device_settings()))
        hw.add(FormRow(tr("settings.refresh"), self.refresh, tr("settings.refresh_hint")))
        self.conflict_warn = ToggleRow(tr("settings.conflict_warning"), s.conflict_warning)
        self.conflict_warn.toggled.connect(lambda v: self._save(conflict_warning=v))
        hw.add(self.conflict_warn)
        self.content.addWidget(hw)

        # ------------------------------------------------------ performance
        perf = Card(tr("settings.performance"))
        self.perf = _combo([(tr("perf.eco"), "eco"), (tr("perf.balanced"), "balanced"), (tr("perf.responsive"), "responsive")], s.performance)
        self.perf.currentIndexChanged.connect(lambda: self._save(performance=self.perf.currentData()))
        perf.add(FormRow(tr("settings.default_performance"), self.perf, tr("settings.performance_hint")))
        self.content.addWidget(perf)

        # ------------------------------------------------------- automation
        auto = Card(tr("settings.automation"), tr("settings.automation_hint"))
        self.auto_enabled = ToggleRow(tr("settings.automation_enabled"), s.automation_enabled)
        self.auto_enabled.toggled.connect(lambda v: (self._save(automation_enabled=v), self.controller.configure_automation()))
        auto.add(self.auto_enabled)
        # night mode
        night = self._rule("night") or AutomationRule("night", "schedule", NIGHT_PRESET_ID, enabled=False)
        self.night_enabled = ToggleRow(tr("settings.night_mode"), night.enabled, tr("settings.night_hint"))
        self.night_start = QTimeEdit(QTime.fromString(night.start, "HH:mm"))
        self.night_end = QTimeEdit(QTime.fromString(night.end, "HH:mm"))
        for te in (self.night_start, self.night_end):
            te.setDisplayFormat("HH:mm")
            te.setButtonSymbols(QTimeEdit.ButtonSymbols.NoButtons)
        self.night_profile = QComboBox()
        nrow = QHBoxLayout()
        nrow.addWidget(label(tr("settings.from"), secondary=True))
        nrow.addWidget(self.night_start)
        nrow.addWidget(label(tr("settings.to"), secondary=True))
        nrow.addWidget(self.night_end)
        nrow.addWidget(self.night_profile, 1)
        auto.add(self.night_enabled)
        auto.add_layout(nrow)
        # fullscreen game
        game = self._rule("fullscreen") or AutomationRule("fullscreen", "fullscreen", GAMING_PRESET_ID, enabled=False)
        self.game_enabled = ToggleRow(tr("settings.game_rule"), game.enabled, tr("settings.game_hint"))
        self.game_profile = QComboBox()
        auto.add(self.game_enabled)
        auto.add(FormRow(tr("settings.profile"), self.game_profile))
        # app rules
        auto.add(label(tr("settings.app_rules"), secondary=True))
        self.app_rules = QListWidget()
        self.app_rules.setMaximumHeight(140)
        auto.add(self.app_rules)
        arow = QHBoxLayout()
        self.app_exe = QLineEdit()
        self.app_exe.setPlaceholderText(tr("settings.exe_placeholder"))
        self.app_profile = QComboBox()
        arow.addWidget(self.app_exe, 2)
        arow.addWidget(self.app_profile, 2)
        arow.addWidget(button(tr("settings.add_rule"), on_click=self._add_app_rule))
        arow.addWidget(button(tr("settings.remove_rule"), ghost=True, on_click=self._remove_app_rule))
        auto.add_layout(arow)
        auto.add(button(tr("settings.save_automation"), primary=True, on_click=self._save_automation))
        self.auto_status = label("", caption=True)
        auto.add(self.auto_status)
        self.content.addWidget(auto)

        # --------------------------------------------------------- recovery
        rec = Card(tr("settings.recovery"))
        self.recovery = ToggleRow(tr("settings.auto_recovery"), s.auto_recovery, tr("settings.auto_recovery_hint"))
        self.recovery.toggled.connect(lambda v: self._save(auto_recovery=v))
        rec.add(self.recovery)
        self.debug = ToggleRow(tr("settings.debug_logging"), s.debug_logging, tr("settings.debug_hint"))
        self.debug.toggled.connect(lambda v: (self._save(debug_logging=v), self.controller.apply_device_settings()))
        rec.add(self.debug)
        self.content.addWidget(rec)

        # -------------------------------------------------------------- logs
        logs = Card(tr("settings.logs"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("Mono")
        self.log_view.setMinimumHeight(220)
        logs.add(self.log_view)
        lrow = QHBoxLayout()
        lrow.addWidget(button(tr("settings.refresh_log"), on_click=self._refresh_log))
        lrow.addWidget(button(tr("settings.open_log_folder"), ghost=True, on_click=lambda: os.startfile(str(log_dir()))))
        lrow.addWidget(button(tr("settings.open_data_folder"), ghost=True, on_click=lambda: os.startfile(str(data_dir()))))
        lrow.addStretch(1)
        logs.add_layout(lrow)
        self.content.addWidget(logs)

        about = Card(tr("settings.about"))
        about.add(label(tr("settings.about_text", version=__version__), wrap=True, secondary=True))
        self.content.addWidget(about)
        self.content.addStretch(1)

        ctx.profilesChanged.connect(self._fill_profile_combos)
        self._fill_profile_combos()

    # ---------------------------------------------------------- helpers
    def _save(self, _theme: bool = False, **changes) -> None:
        self.ctx.save_settings(**changes)
        if _theme:
            self.ctx.notify.emit(tr("settings.theme_restart"), "info")

    def _rule(self, rid: str) -> AutomationRule | None:
        return next((r for r in self.ctx.settings.automation if r.id == rid), None)

    def _fill_profile_combos(self) -> None:
        profiles = sorted(self.controller.profiles.list(), key=lambda p: p.name.lower())
        s = self.ctx.settings
        self.startup.blockSignals(True)
        self.startup.clear()
        self.startup.addItem(tr("settings.startup_last"), "last")
        self.startup.addItem(tr("settings.startup_none"), "none")
        for p in profiles:
            self.startup.addItem(p.name, p.id)
        self.startup.setCurrentIndex(max(0, self.startup.findData(s.startup_profile)))
        self.startup.blockSignals(False)
        night = self._rule("night")
        game = self._rule("fullscreen")
        for combo, current in ((self.night_profile, night.profile_id if night else NIGHT_PRESET_ID),
                               (self.game_profile, game.profile_id if game else GAMING_PRESET_ID),
                               (self.app_profile, GAMING_PRESET_ID)):
            combo.clear()
            for p in profiles:
                combo.addItem(p.name, p.id)
            combo.setCurrentIndex(max(0, combo.findData(current)))
        self.app_rules.clear()
        for r in s.automation:
            if r.kind == "process":
                prof = self.controller.profiles.get(r.profile_id)
                it = QListWidgetItem(f"{', '.join(r.processes)}  →  {prof.name if prof else r.profile_id}")
                it.setData(256, r.id)
                self.app_rules.addItem(it)

    def _add_app_rule(self) -> None:
        exe = self.app_exe.text().strip().lower()
        if not exe:
            return
        if not exe.endswith(".exe"):
            exe += ".exe"
        rules = list(self.ctx.settings.automation)
        rules.append(AutomationRule(uuid.uuid4().hex[:8], "process", self.app_profile.currentData(), processes=[exe]))
        self.ctx.save_settings(automation=rules)
        self.app_exe.clear()
        self._fill_profile_combos()
        self.controller.configure_automation()

    def _remove_app_rule(self) -> None:
        it = self.app_rules.currentItem()
        if not it:
            return
        rid = it.data(256)
        self.ctx.save_settings(automation=[r for r in self.ctx.settings.automation if r.id != rid])
        self._fill_profile_combos()
        self.controller.configure_automation()

    def _save_automation(self) -> None:
        rules = [r for r in self.ctx.settings.automation if r.id not in ("night", "fullscreen")]
        rules.append(AutomationRule("night", "schedule", self.night_profile.currentData() or NIGHT_PRESET_ID,
                                    enabled=self.night_enabled.isChecked(),
                                    start=self.night_start.time().toString("HH:mm"), end=self.night_end.time().toString("HH:mm")))
        rules.append(AutomationRule("fullscreen", "fullscreen", self.game_profile.currentData() or GAMING_PRESET_ID,
                                    enabled=self.game_enabled.isChecked()))
        self.ctx.save_settings(automation=rules)
        self.controller.configure_automation()
        self.ctx.notify.emit(tr("settings.automation_saved"), "success")

    def _language_changed(self) -> None:
        self._save(language=self.language.currentData())
        QMessageBox.information(self, tr("settings.language"), tr("settings.restart_hint"))

    def _backend_changed(self) -> None:
        self._save(capture_backend=self.backend.currentData())
        self.controller.apply_capture_settings()

    def _autostart_changed(self, on: bool) -> None:
        if not autostart.set_enabled(on):
            self.ctx.notify.emit(tr("settings.autostart_failed"), "danger")
        self._save(start_with_windows=on)

    def _refresh_log(self) -> None:
        self.log_view.setPlainText("\n".join(MEMORY.tail(400)))
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def on_shown(self) -> None:
        self._refresh_log()

    def update_snapshot(self, snap: AppSnapshot) -> None:
        if snap.automation_rule:
            self.auto_status.setText(tr("settings.automation_active", rule=snap.automation_rule))
        else:
            self.auto_status.setText(tr("settings.automation_idle") if self.ctx.settings.automation_enabled else "")
