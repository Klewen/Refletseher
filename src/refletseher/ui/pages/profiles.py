"""Profiles page: create, edit, delete, duplicate, import/export, default."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMessageBox

from ...core.controller import AppSnapshot
from ...i18n import tr
from ...profiles.model import LightMode, Profile
from ..base import Page, UiContext, algo_name, effect_name
from ..widgets.common import Card, ColorChip, button, label

MODE_KEYS = {LightMode.STATIC: "mode.static", LightMode.EFFECT: "mode.effect", LightMode.SCREEN_SYNC: "mode.screen_sync", LightMode.OFF: "mode.off"}


class ProfilesPage(Page):
    key = "profiles"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("profiles.title"), tr("profiles.subtitle"))
        self.actions.addWidget(button(tr("profiles.import"), on_click=self._import))
        self.actions.addWidget(button(tr("profiles.export_all"), on_click=self._export_all))
        self.actions.addWidget(button(tr("profiles.new"), primary=True, on_click=self._new))

        cols = QHBoxLayout()
        cols.setSpacing(16)
        left = Card(tr("profiles.list"))
        self.list = QListWidget()
        self.list.setMinimumWidth(300)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self.list.itemDoubleClicked.connect(lambda *_: self._apply())
        left.add(self.list, 1)
        left.add(button(tr("profiles.restore_presets"), ghost=True, on_click=self._restore_presets))
        cols.addWidget(left, 2)

        detail = Card(tr("profiles.details"))
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.setPlaceholderText(tr("profiles.name_prompt"))
        detail.add(label(tr("profiles.name"), secondary=True))
        row = QHBoxLayout()
        row.addWidget(self.name, 1)
        row.addWidget(button(tr("profiles.rename"), on_click=self._rename))
        detail.add_layout(row)
        self.meta = label("", secondary=True, wrap=True)
        self.desc = label("", caption=True, wrap=True)
        detail.add(self.meta)
        detail.add(self.desc)
        chips = QHBoxLayout()
        self.chips = [ColorChip(None, height=34) for _ in range(4)]
        for c in self.chips:
            chips.addWidget(c)
        detail.add_layout(chips)
        self.badges = label("", caption=True)
        detail.add(self.badges)
        b1 = QHBoxLayout()
        b1.addWidget(button(tr("profiles.apply"), primary=True, on_click=self._apply))
        b1.addWidget(button(tr("profiles.update_from_current"), on_click=self._update_from_current))
        b1.addWidget(button(tr("profiles.set_default"), on_click=self._set_default))
        b1.addStretch(1)
        detail.add_layout(b1)
        b2 = QHBoxLayout()
        b2.addWidget(button(tr("profiles.duplicate"), on_click=self._duplicate))
        b2.addWidget(button(tr("profiles.export"), on_click=self._export_selected))
        b2.addStretch(1)
        b2.addWidget(button(tr("profiles.delete"), danger=True, on_click=self._delete))
        detail.add_layout(b2)
        detail.body.addStretch(1)
        cols.addWidget(detail, 3)
        self.content.addLayout(cols, 1)
        ctx.profilesChanged.connect(self.reload)
        ctx.settingsChanged.connect(self._refresh_labels)
        self.reload()

    # ------------------------------------------------------------- data
    def _selected(self) -> Profile | None:
        it = self.list.currentItem()
        return self.controller.profiles.get(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def reload(self) -> None:
        cur = self._selected()
        cur_id = cur.id if cur else self.ctx.settings.last_profile_id
        self.list.blockSignals(True)
        self.list.clear()
        profiles = sorted(self.controller.profiles.list(), key=lambda p: (not p.builtin, p.name.lower()))
        for p in profiles:
            it = QListWidgetItem(self._item_text(p))
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            self.list.addItem(it)
            if p.id == cur_id:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self._show_selected()

    def _item_text(self, p: Profile) -> str:
        marks = []
        if p.id == self.ctx.settings.default_profile_id:
            marks.append("★")
        if p.builtin:
            marks.append(tr("profiles.builtin_mark"))
        return f"{p.name}   ·   {tr(MODE_KEYS[p.mode])}" + (f"   {' '.join(marks)}" if marks else "")

    def _refresh_labels(self) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            p = self.controller.profiles.get(it.data(Qt.ItemDataRole.UserRole))
            if p:
                it.setText(self._item_text(p))

    def _show_selected(self) -> None:
        p = self._selected()
        if p is None:
            self.name.setText("")
            self.meta.setText(tr("profiles.none_selected"))
            self.desc.setText("")
            for c in self.chips:
                c.set_color(None)
            return
        self.name.setText(p.name)
        if p.mode == LightMode.SCREEN_SYNC:
            detail = f"{tr('mode.screen_sync')} · {algo_name(p.sync.analysis.mode.value)} · {tr('perf.' + p.sync.performance)}"
            colors = [None] * 4
        elif p.mode == LightMode.EFFECT:
            detail = f"{tr('mode.effect')} · {effect_name(p.effect.effect)}"
            cols = p.effect.effective_colors()
            colors = [cols[i % len(cols)] for i in range(4)]
        elif p.mode == LightMode.OFF:
            detail = tr("mode.off")
            colors = [(0, 0, 0)] * 4
        else:
            detail = tr("mode.static")
            colors = list(p.static.zone_colors)
        self.meta.setText(f"{detail} · {tr('profiles.brightness', v=p.master_brightness)}")
        self.desc.setText(tr(p.description) if p.description.startswith("preset.") else p.description)
        for c, col in zip(self.chips, colors):
            c.set_color(col)
        marks = []
        if p.id == self.ctx.settings.default_profile_id:
            marks.append(tr("profiles.is_default"))
        if p.builtin:
            marks.append(tr("profiles.is_builtin"))
        self.badges.setText(" · ".join(marks))

    # ---------------------------------------------------------- actions
    def _apply(self) -> None:
        p = self._selected()
        if p and self.controller.apply_profile(p.id):
            self.ctx.settingsChanged.emit()
            self.ctx.notify.emit(tr("profiles.applied", name=p.name), "success")

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, tr("profiles.new"), tr("profiles.name_prompt"),
                                        text=self.controller.profiles.unique_name(tr("profiles.new_name")))
        if ok and name.strip():
            p = self.controller.profiles.put(self.controller.current_as_profile(name.strip()))
            self.ctx.profilesChanged.emit()
            self._select_id(p.id)

    def _select_id(self, pid: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == pid:
                self.list.setCurrentRow(i)
                return

    def _rename(self) -> None:
        p = self._selected()
        name = self.name.text().strip()
        if p and name:
            p.name = name[:60]
            self.controller.profiles.put(p)
            self.ctx.profilesChanged.emit()

    def _update_from_current(self) -> None:
        p = self._selected()
        if not p:
            return
        if QMessageBox.question(self, tr("profiles.update_from_current"), tr("profiles.confirm_overwrite", name=p.name)) != QMessageBox.StandardButton.Yes:
            return
        newp = self.controller.current_as_profile(p.name, pid=p.id)
        newp.builtin, newp.description = p.builtin, p.description
        self.controller.profiles.put(newp)
        self.ctx.profilesChanged.emit()

    def _duplicate(self) -> None:
        p = self._selected()
        if p:
            d = self.controller.profiles.duplicate(p.id, self.controller.profiles.unique_name(p.name))
            self.ctx.profilesChanged.emit()
            self._select_id(d.id)

    def _delete(self) -> None:
        p = self._selected()
        if not p:
            return
        if QMessageBox.question(self, tr("profiles.delete"), tr("profiles.confirm_delete", name=p.name)) != QMessageBox.StandardButton.Yes:
            return
        self.controller.profiles.delete(p.id)
        s = self.ctx.settings
        if s.default_profile_id == p.id:
            self.ctx.save_settings(default_profile_id=None)
        self.ctx.profilesChanged.emit()

    def _set_default(self) -> None:
        p = self._selected()
        if p:
            self.ctx.save_settings(default_profile_id=p.id)
            self._show_selected()
            self.ctx.notify.emit(tr("profiles.default_set", name=p.name), "success")

    def _restore_presets(self) -> None:
        n = self.controller.profiles.restore_presets()
        self.ctx.profilesChanged.emit()
        self.ctx.notify.emit(tr("profiles.presets_restored", n=n), "info")

    def _export_selected(self) -> None:
        p = self._selected()
        if p:
            self._export([p.id], f"{p.name}.json")

    def _export_all(self) -> None:
        self._export([p.id for p in self.controller.profiles.list()], "Refletseher-profiles.json")

    def _export(self, ids: list[str], default_name: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("profiles.export"), default_name, "JSON (*.json)")
        if path:
            n = self.controller.profiles.export(ids, path)
            self.ctx.notify.emit(tr("profiles.exported", n=n), "success")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("profiles.import"), "", "JSON (*.json)")
        if not path:
            return
        imported, errors = self.controller.profiles.import_file(path)
        self.ctx.profilesChanged.emit()
        msg = tr("profiles.imported", n=len(imported))
        if errors:
            QMessageBox.warning(self, tr("profiles.import"), msg + "\n\n" + "\n".join(errors[:10]))
        else:
            self.ctx.notify.emit(msg, "success")

    def update_snapshot(self, snap: AppSnapshot) -> None:
        pass
