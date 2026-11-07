"""Dashboard: status overview, big keyboard preview, quick actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout

from ...core.controller import AppSnapshot, Mode
from ...i18n import tr
from ...rgb import to_hex
from ..base import Page, UiContext, device_status, fmt_age, keyboard_badge, mode_text
from ..widgets.common import Banner, Card, ColorChip, StatusPill, Swatch, button, label
from ..widgets.keyboard_view import KeyboardView

QUICK_COLORS = [(255, 0, 0), (255, 80, 0), (255, 200, 0), (0, 230, 90), (0, 220, 220), (0, 80, 255), (150, 0, 255), (255, 0, 160), (255, 240, 225)]
QUICK_PROFILES = ["preset_cinematic", "preset_gaming", "preset_adaptive", "preset_rainbow", "preset_night"]


class DashboardPage(Page):
    key = "dashboard"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("dashboard.title"), tr("dashboard.subtitle"))
        self.sync_btn = button(tr("sync.start"), primary=True, on_click=self.controller.toggle_sync)
        self.actions.addWidget(self.sync_btn)

        self.conflict = Banner("warning")
        self.content.addWidget(self.conflict)

        hero = Card()
        self.keyboard = KeyboardView(interactive=True)
        self.keyboard.setMinimumHeight(300)
        self.keyboard.set_zone_labels([tr("zone.n", n=i + 1) for i in range(4)])
        self.keyboard.zoneClicked.connect(lambda z, add: ctx.navigate.emit("studio", z))
        hero.add(self.keyboard, 1)
        row = QHBoxLayout()
        self.power_btn = button(tr("rgb.turn_off"), on_click=self._toggle_power)
        self.undo_btn = button(tr("rgb.undo"), ghost=True, on_click=self.controller.undo)
        row.addWidget(self.power_btn)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        row.addWidget(label(tr("dashboard.click_zone_hint"), caption=True))
        hero.add_layout(row)
        self.content.addWidget(hero)

        grid = QGridLayout()
        grid.setSpacing(16)
        # device card
        dev = Card(tr("dashboard.device"))
        self.dev_pill = StatusPill()
        dev.header.addWidget(self.dev_pill, 0, Qt.AlignmentFlag.AlignTop)
        self.dev_name = label("", secondary=True)
        self.dev_last = label("", caption=True)
        self.dev_errors = label("", caption=True)
        dev.add(self.dev_name)
        dev.add(self.dev_last)
        dev.add(self.dev_errors)
        dev.add(button(tr("dashboard.hardware_details"), ghost=True, on_click=lambda: ctx.navigate.emit("hardware", None)))
        grid.addWidget(dev, 0, 0)
        # mode card
        mode = Card(tr("dashboard.active_mode"))
        self.mode_label = label("", "Metric")
        self.mode_label.setWordWrap(True)
        self.profile_label = label("", secondary=True)
        self.mode_detail = label("", caption=True, wrap=True)
        mode.add(self.mode_label)
        mode.add(self.profile_label)
        mode.add(self.mode_detail)
        grid.addWidget(mode, 0, 1)
        # zone colours card
        zones = Card(tr("dashboard.zone_colors"), tr("dashboard.zone_colors_hint"))
        zg = QGridLayout()
        zg.setSpacing(8)
        self.zone_chips: list[ColorChip] = []
        self.zone_hex: list = []
        for i in range(4):
            chip = ColorChip(None, height=30)
            self.zone_chips.append(chip)
            hx = label("—", caption=True)
            hx.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.zone_hex.append(hx)
            zg.addWidget(chip, 0, i)
            zg.addWidget(hx, 1, i)
        zones.add_layout(zg)
        grid.addWidget(zones, 0, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self.content.addLayout(grid)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        quick = Card(tr("dashboard.quick_colors"), tr("dashboard.quick_colors_hint"))
        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        for c in QUICK_COLORS:
            sw = Swatch(c, 30)
            sw.clicked.connect(lambda _=False, col=c: self.controller.set_all(col))
            qrow.addWidget(sw)
        off = button(tr("rgb.off_short"), ghost=True, on_click=lambda: self.controller.set_power(False))
        qrow.addWidget(off)
        qrow.addStretch(1)
        quick.add_layout(qrow)
        modes_row = QHBoxLayout()
        modes_row.setSpacing(8)
        self.quick_profile_buttons = []
        for pid in QUICK_PROFILES:
            b = button("", chip=False, on_click=lambda _=False, p=pid: self._apply(p))
            b.setProperty("pid", pid)
            self.quick_profile_buttons.append(b)
            modes_row.addWidget(b)
        modes_row.addStretch(1)
        quick.add(label(tr("dashboard.quick_modes"), secondary=True))
        quick.add_layout(modes_row)
        bottom.addWidget(quick, 3)

        recent = Card(tr("dashboard.recent_profiles"))
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(6)
        recent.add_layout(self.recent_box)
        recent.body.addStretch(1)
        bottom.addWidget(recent, 2)
        self.content.addLayout(bottom)
        self.content.addStretch(1)

        ctx.profilesChanged.connect(self._refresh_profiles)
        ctx.settingsChanged.connect(self._refresh_profiles)
        self._refresh_profiles()

    def _apply(self, pid: str) -> None:
        if self.controller.apply_profile(pid):
            self.ctx.settingsChanged.emit()

    def _toggle_power(self) -> None:
        self.controller.set_power(not self.controller.state.power)

    def _refresh_profiles(self) -> None:
        store = self.controller.profiles
        for b in self.quick_profile_buttons:
            p = store.get(b.property("pid"))
            b.setVisible(p is not None)
            if p:
                b.setText(p.name)
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        recent = [store.get(pid) for pid in self.ctx.settings.recent_profiles]
        recent = [p for p in recent if p is not None][:5]
        if not recent:
            self.recent_box.addWidget(label(tr("dashboard.no_recent"), caption=True))
        for p in recent:
            b = button(p.name, ghost=True, on_click=lambda _=False, pid=p.id: self._apply(pid))
            b.setStyleSheet("text-align: left;")
            self.recent_box.addWidget(b)

    def update_snapshot(self, snap: AppSnapshot) -> None:
        self.keyboard.set_colors(snap.intended)
        self.keyboard.set_badge(*keyboard_badge(snap))
        text, level = device_status(snap.device, snap.simulation_backend)
        self.dev_pill.set_status(text, level)
        d = snap.device
        self.dev_name.setText(d.device.label if d.device else tr("device.no_device"))
        self.dev_last.setText(tr("dashboard.last_update", when=fmt_age(d.last_written_at)))
        self.dev_errors.setText(tr("dashboard.error_count", n=d.error_count) + (f" · {d.last_error}" if d.last_error and not d.connected else ""))
        self.mode_label.setText(mode_text(snap))
        self.profile_label.setText(tr("dashboard.profile", name=snap.profile_name) if snap.profile_name else tr("dashboard.no_profile"))
        detail = ""
        if snap.mode == Mode.SCREEN_SYNC and snap.sync:
            s = snap.sync
            detail = tr("dashboard.sync_detail", fps=f"{s.analysis_fps:.0f}", ms=f"{s.pipeline_ms:.1f}", hz=f"{d.updates_per_sec:.1f}")
        elif snap.simulated:
            detail = tr("dashboard.hw_effect_detail")
        self.mode_detail.setText(detail)
        colors = snap.intended or (None, None, None, None)
        for i in range(4):
            self.zone_chips[i].set_color(colors[i])
            self.zone_hex[i].setText(to_hex(colors[i]) if colors[i] else "—")
        running = snap.mode == Mode.SCREEN_SYNC
        self.sync_btn.setText(tr("sync.stop") if running else tr("sync.start"))
        self.power_btn.setText(tr("rgb.turn_off") if snap.power else tr("rgb.turn_on"))
        self.undo_btn.setEnabled(snap.can_undo)
        if snap.conflict.has_conflict and self.ctx.settings.conflict_warning:
            self.conflict.show_message(tr("conflict.banner", apps=snap.conflict.summary), "warning")
        else:
            self.conflict.show_message("")
