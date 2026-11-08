"""RGB Studio: manual per-zone colour control."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QInputDialog, QMenu, QVBoxLayout, QWidget

from ...core.controller import AppSnapshot
from ...i18n import tr
from ...rgb import RGB, from_hex, to_hex
from ..base import Page, UiContext, keyboard_badge
from ..widgets.color_picker import ColorPicker
from ..widgets.common import Card, SliderRow, Swatch, button, label
from ..widgets.keyboard_view import KeyboardView

PALETTE = [
    (255, 0, 0), (255, 60, 0), (255, 140, 0), (255, 210, 0), (190, 255, 0), (0, 255, 60),
    (0, 255, 170), (0, 230, 255), (0, 120, 255), (0, 40, 255), (110, 0, 255), (190, 0, 255),
    (255, 0, 200), (255, 0, 90), (255, 240, 225), (255, 255, 255),
]


class RgbStudioPage(Page):
    key = "studio"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("studio.title"), tr("studio.subtitle"))
        self._selected: set[int] = {0, 1, 2, 3}
        self.save_btn = button(tr("studio.save_profile"), on_click=self._save_profile)
        self.actions.addWidget(self.save_btn)

        top = QHBoxLayout()
        top.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)

        kb_card = Card(tr("studio.keyboard"), tr("studio.keyboard_hint"))
        self.keyboard = KeyboardView(interactive=True)
        self.keyboard.setMinimumHeight(260)
        self.keyboard.set_zone_labels([tr("zone.n", n=i + 1) for i in range(4)])
        self.keyboard.zoneClicked.connect(self._zone_clicked)
        kb_card.add(self.keyboard, 1)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.zone_buttons = []
        for i in range(4):
            b = button(tr("zone.n", n=i + 1), chip=True)
            b.clicked.connect(lambda _=False, z=i: self._toggle_zone(z))
            self.zone_buttons.append(b)
            chips.addWidget(b)
        chips.addWidget(button(tr("studio.select_all"), ghost=True, on_click=lambda: self._set_selection({0, 1, 2, 3})))
        chips.addStretch(1)
        kb_card.add_layout(chips)
        left.addWidget(kb_card, 1)

        bright = Card(tr("studio.brightness"))
        self.master = SliderRow(tr("studio.master_brightness"), 0, 100, 100, "%")
        self.master.valueChanged.connect(self.controller.set_master_brightness)
        self.zone_bright = SliderRow(tr("studio.zone_brightness"), 0, 100, 100, "%")
        self.zone_bright.valueChanged.connect(self._zone_brightness_changed)
        bright.add(self.master)
        bright.add(self.zone_bright)
        row = QHBoxLayout()
        self.power_btn = button(tr("rgb.turn_off"), on_click=self._toggle_power)
        self.undo_btn = button(tr("rgb.undo"), ghost=True, on_click=self.controller.undo)
        row.addWidget(self.power_btn)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        bright.add_layout(row)
        left.addWidget(bright)
        top.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(16)
        pick = Card(tr("studio.color"))
        self.picker = ColorPicker((255, 0, 40))
        self.picker.colorChanged.connect(self._color_changed)
        pick.add(self.picker, 1)
        btns = QHBoxLayout()
        btns.addWidget(button(tr("studio.apply_selected"), primary=True, on_click=self._apply_selected))
        btns.addWidget(button(tr("studio.apply_all"), on_click=self._apply_all))
        pick.add_layout(btns)
        right.addWidget(pick, 1)

        pal = Card(tr("studio.palette"))
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, c in enumerate(PALETTE):
            sw = Swatch(c, 28)
            sw.clicked.connect(lambda _=False, col=c: self._pick_swatch(col))
            grid.addWidget(sw, i // 8, i % 8)
        pal.add_layout(grid)
        fav_head = QHBoxLayout()
        fav_head.addWidget(label(tr("studio.favorites"), secondary=True), 1)
        fav_head.addWidget(button(tr("studio.add_favorite"), ghost=True, on_click=self._add_favorite))
        pal.add_layout(fav_head)
        self.fav_row = QHBoxLayout()
        self.fav_row.setSpacing(8)
        pal.add_layout(self.fav_row)
        pal.add(label(tr("studio.favorites_hint"), caption=True))
        right.addWidget(pal)
        top.addLayout(right, 2)
        self.content.addLayout(top)
        self.content.addStretch(1)
        self._refresh_favorites()
        self._set_selection({0, 1, 2, 3})

    # ---------------------------------------------------------- selection
    def select_zone(self, z: int) -> None:
        self._set_selection({z})

    def _set_selection(self, zones: set[int]) -> None:
        self._selected = set(zones) or {0}
        for i, b in enumerate(self.zone_buttons):
            b.setChecked(i in self._selected)
        self.keyboard.set_selected(self._selected)
        st = self.controller.state.static
        first = min(self._selected)
        self.picker.set_color(st.zone_colors[first])
        self.zone_bright.setValue(st.zone_brightness[first])

    def _toggle_zone(self, z: int) -> None:
        sel = set(self._selected)
        sel.symmetric_difference_update({z})
        self._set_selection(sel)

    def _zone_clicked(self, z: int, additive: bool) -> None:
        if additive:
            self._toggle_zone(z)
        else:
            self._set_selection({z})

    # ------------------------------------------------------------- colour
    def _color_changed(self, r: int, g: int, b: int) -> None:
        self.controller.set_zone_color(sorted(self._selected), (r, g, b))

    def _pick_swatch(self, c: RGB) -> None:
        self.picker.set_color(c)
        self.controller.set_zone_color(sorted(self._selected), c)

    def _apply_selected(self) -> None:
        self.controller.set_zone_color(sorted(self._selected), self.picker.color())

    def _apply_all(self) -> None:
        self.controller.set_all(self.picker.color())
        self._set_selection({0, 1, 2, 3})

    def _zone_brightness_changed(self, v: int) -> None:
        br = list(self.controller.state.static.zone_brightness)
        for z in self._selected:
            br[z] = v
        self.controller.set_static(zone_brightness=br)

    def _toggle_power(self) -> None:
        self.controller.set_power(not self.controller.state.power)

    # ---------------------------------------------------------- favourites
    def _refresh_favorites(self) -> None:
        while self.fav_row.count():
            it = self.fav_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for hx in self.ctx.settings.favorites:
            try:
                c = from_hex(hx)
            except ValueError:
                continue
            sw = Swatch(c, 28)
            sw.clicked.connect(lambda _=False, col=c: self._pick_swatch(col))
            sw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            sw.customContextMenuRequested.connect(lambda _pos, h=hx, w=sw: self._fav_menu(h, w))
            self.fav_row.addWidget(sw)
        self.fav_row.addStretch(1)

    def _fav_menu(self, hx: str, w: QWidget) -> None:
        m = QMenu(self)
        act = m.addAction(tr("studio.remove_favorite"))
        if m.exec(w.mapToGlobal(w.rect().bottomLeft())) == act:
            favs = [f for f in self.ctx.settings.favorites if f != hx]
            self.ctx.save_settings(favorites=favs)
            self._refresh_favorites()

    def _add_favorite(self) -> None:
        hx = to_hex(self.picker.color())
        favs = [f for f in self.ctx.settings.favorites if f.upper() != hx] + [hx]
        self.ctx.save_settings(favorites=favs[-16:])
        self._refresh_favorites()

    # ------------------------------------------------------------ profiles
    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, tr("studio.save_profile"), tr("profiles.name_prompt"),
                                        text=self.controller.profiles.unique_name(tr("profiles.new_name")))
        if not ok or not name.strip():
            return
        prof = self.controller.current_as_profile(name.strip())
        self.controller.profiles.put(prof)
        self.ctx.profilesChanged.emit()
        self.ctx.notify.emit(tr("profiles.saved", name=prof.name), "success")

    def on_shown(self) -> None:
        self.master.setValue(self.controller.state.master_brightness)
        self._set_selection(self._selected)

    def update_snapshot(self, snap: AppSnapshot) -> None:
        self.keyboard.set_colors(snap.intended)
        self.keyboard.set_badge(*keyboard_badge(snap))
        self.power_btn.setText(tr("rgb.turn_off") if snap.power else tr("rgb.turn_on"))
        self.undo_btn.setEnabled(snap.can_undo)
        if not self.master.slider.isSliderDown():
            self.master.setValue(snap.master_brightness)
