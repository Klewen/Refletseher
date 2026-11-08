"""Screen Sync page: source, algorithm, tuning, live analysis preview, metrics."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ...capture.monitors import enumerate_monitors
from ...color.settings import AnalysisSettings, OutputSettings, SpatialWeighting, SyncMode, TransitionSettings
from ...core.controller import AppSnapshot, Mode
from ...i18n import tr
from ...profiles.model import SyncProfile
from ..base import Page, UiContext, algo_name, keyboard_badge
from ..theme import tokens
from ..widgets.common import Banner, Card, ColorChip, FormRow, MetricTile, Segmented, SliderRow, ToggleRow, button, label
from ..widgets.keyboard_view import KeyboardView


class AnalysisPreview(QWidget):
    """Shows the in-memory analysis frame (never stored) with overlays."""

    def __init__(self) -> None:
        super().__init__()
        self._img: QImage | None = None
        self._crop = (0, 0, 0, 0)
        self._spatial = False
        self._size = (160, 90)
        self.setMinimumHeight(180)
        self.setMaximumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_frame(self, frame: np.ndarray | None, crop: tuple[int, int, int, int], spatial: bool) -> None:
        if frame is None:
            if self._img is not None:
                self._img = None
                self.update()
            return
        h, w = frame.shape[:2]
        arr = np.ascontiguousarray(frame)
        self._img = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._crop, self._spatial, self._size = crop, spatial, (w, h)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(t.border), 1))
        p.setBrush(QColor(t.chassis))
        p.drawRoundedRect(area, 10, 10)
        if self._img is None:
            p.setPen(QColor(t.muted))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, tr("sync.preview_empty"))
            return
        w, h = self._size
        scale = min(area.width() / w, area.height() / h)
        dw, dh = w * scale, h * scale
        r = QRectF(area.center().x() - dw / 2, area.center().y() - dh / 2, dw, dh)
        p.drawImage(r, self._img)
        top, bottom, left, right = self._crop
        p.setBrush(QColor(0, 0, 0, 120))
        p.setPen(Qt.PenStyle.NoPen)
        if top:
            p.drawRect(QRectF(r.left(), r.top(), r.width(), top * scale))
        if bottom:
            p.drawRect(QRectF(r.left(), r.bottom() - bottom * scale, r.width(), bottom * scale))
        if left:
            p.drawRect(QRectF(r.left(), r.top(), left * scale, r.height()))
        if right:
            p.drawRect(QRectF(r.right() - right * scale, r.top(), right * scale, r.height()))
        if top or bottom or left or right:
            pen = QPen(QColor(t.warning), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(r.left() + left * scale, r.top() + top * scale, r.width() - (left + right) * scale, r.height() - (top + bottom) * scale))
        if self._spatial:
            pen = QPen(QColor(255, 255, 255, 140), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            inner_l = r.left() + left * scale
            inner_w = r.width() - (left + right) * scale
            for i in range(1, 4):
                x = inner_l + inner_w * i / 4
                p.drawLine(int(x), int(r.top()), int(x), int(r.bottom()))


MODES = [SyncMode.DOMINANT, SyncMode.PALETTE, SyncMode.SPATIAL, SyncMode.CINEMATIC, SyncMode.ADAPTIVE]


class ScreenSyncPage(Page):
    key = "sync"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx, tr("sync.title"), tr("sync.subtitle"))
        self._sp: SyncProfile = self.controller.state.sync
        self._loading = False
        self.start_btn = button(tr("sync.start"), primary=True, on_click=self._toggle)
        self.actions.addWidget(self.start_btn)

        self.banner = Banner("info")
        self.content.addWidget(self.banner)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)

        # --- source
        src = Card(tr("sync.source"))
        self.monitor = QComboBox()
        self.monitor.currentIndexChanged.connect(self._monitor_changed)
        mon_row = QHBoxLayout()
        mon_row.addWidget(self.monitor, 1)
        mon_row.addWidget(button(icon="", tooltip=tr("sync.refresh_monitors"), on_click=self._load_monitors))
        mw = QWidget()
        mw.setLayout(mon_row)
        mon_row.setContentsMargins(0, 0, 0, 0)
        src.add(FormRow(tr("sync.monitor"), mw))
        self.backend = QComboBox()
        for key in ("auto", "dxgi", "winrt", "gdi"):
            self.backend.addItem(tr(f"backend.{key}"), key)
        self.backend.currentIndexChanged.connect(self._backend_changed)
        src.add(FormRow(tr("sync.backend"), self.backend, tr("sync.backend_hint")))
        self.perf = Segmented([("eco", tr("perf.eco")), ("balanced", tr("perf.balanced")), ("responsive", tr("perf.responsive"))])
        self.perf.changed.connect(self._perf_changed)
        src.add(label(tr("sync.performance"), secondary=True))
        src.add(self.perf)
        self.perf_hint = label("", caption=True, wrap=True)
        src.add(self.perf_hint)
        # region
        reg = QHBoxLayout()
        reg.setSpacing(6)
        self.region_spins = []
        for key in ("x", "y", "w", "h"):
            sp = QDoubleSpinBox()
            sp.setRange(0, 100)
            sp.setDecimals(0)
            sp.setSuffix("%")
            sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            sp.setPrefix(f"{key.upper()} ")
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(self._region_changed)
            self.region_spins.append(sp)
            reg.addWidget(sp)
        reg.addWidget(button(tr("sync.full_screen"), ghost=True, on_click=self._region_full))
        rw = QWidget()
        rw.setLayout(reg)
        reg.setContentsMargins(0, 0, 0, 0)
        src.add(label(tr("sync.region"), secondary=True))
        src.add(rw)
        src.add(label(tr("sync.region_hint"), caption=True, wrap=True))
        left.addWidget(src)

        # --- algorithm
        algo = Card(tr("sync.algorithm"))
        self.mode = Segmented([(m.value, algo_name(m.value)) for m in MODES])
        self.mode.changed.connect(self._mode_changed)
        algo.add(self.mode)
        self.mode_desc = label("", caption=True, wrap=True)
        algo.add(self.mode_desc)
        self.weighting = QComboBox()
        for w in SpatialWeighting:
            self.weighting.addItem(tr(f"weighting.{w.value}"), w.value)
        self.weighting.currentIndexChanged.connect(self._changed)
        algo.add(FormRow(tr("sync.weighting"), self.weighting))
        self.letterbox = ToggleRow(tr("sync.letterbox"), True, tr("sync.letterbox_hint"))
        self.letterbox.toggled.connect(self._changed)
        self.subtitle = ToggleRow(tr("sync.subtitle_guard"), True, tr("sync.subtitle_guard_hint"))
        self.subtitle.toggled.connect(self._changed)
        self.cut_fast = ToggleRow(tr("sync.scene_cut"), True, tr("sync.scene_cut_hint"))
        self.cut_fast.toggled.connect(self._changed)
        self.flash_guard = ToggleRow(tr("sync.flash_guard"), True, tr("sync.flash_guard_hint"))
        self.flash_guard.toggled.connect(self._changed)
        for w in (self.letterbox, self.subtitle, self.cut_fast, self.flash_guard):
            algo.add(w)
        left.addWidget(algo)

        # --- tuning
        tune = Card(tr("sync.tuning"))
        self.s_sensitivity = SliderRow(tr("sync.sensitivity"), 0, 100, 60, tooltip=tr("sync.sensitivity_hint"))
        self.s_speed = SliderRow(tr("sync.transition_speed"), 0, 100, 55, tooltip=tr("sync.transition_speed_hint"))
        self.s_smooth = SliderRow(tr("sync.smoothing"), 0, 100, 45, tooltip=tr("sync.smoothing_hint"))
        self.s_bright = SliderRow(tr("sync.brightness"), 0, 100, 100, "%")
        self.s_sat = SliderRow(tr("sync.saturation"), 0, 200, 115, "%")
        self.s_black = SliderRow(tr("sync.black_level"), 0, 40, 16, fmt=lambda v: f"{v}%", tooltip=tr("sync.black_level_hint"))
        self.s_mindiff = SliderRow(tr("sync.min_diff"), 0, 12, 2, tooltip=tr("sync.min_diff_hint"))
        self.s_rate = SliderRow(tr("sync.update_rate"), 1, 15, 10, " Hz", tooltip=tr("sync.update_rate_hint"))
        for s in (self.s_sensitivity, self.s_speed, self.s_smooth, self.s_bright, self.s_sat, self.s_black, self.s_mindiff):
            s.valueChanged.connect(self._changed)
            tune.add(s)
        self.s_rate.valueChanged.connect(self._rate_changed)
        tune.add(self.s_rate)
        tune.add(button(tr("sync.reset_defaults"), ghost=True, on_click=self._reset_defaults))
        left.addWidget(tune)
        left.addStretch(1)
        cols.addLayout(left, 5)

        # --- right column: preview + metrics
        right = QVBoxLayout()
        right.setSpacing(16)
        prev = Card(tr("sync.preview"), tr("sync.preview_hint"))
        self.preview = AnalysisPreview()
        prev.add(self.preview, 1)
        self.palette_row = QHBoxLayout()
        self.palette_row.setSpacing(6)
        self.palette_chips = [ColorChip(None, height=18) for _ in range(6)]
        for c in self.palette_chips:
            self.palette_row.addWidget(c)
        prev.add(label(tr("sync.detected_palette"), secondary=True))
        prev.add_layout(self.palette_row)
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(label(tr("sync.targets"), caption=True), 0, 0)
        grid.addWidget(label(tr("sync.output"), caption=True), 1, 0)
        self.target_chips = [ColorChip(None, height=24) for _ in range(4)]
        self.output_chips = [ColorChip(None, height=24) for _ in range(4)]
        for i in range(4):
            grid.addWidget(self.target_chips[i], 0, i + 1)
            grid.addWidget(self.output_chips[i], 1, i + 1)
        prev.add_layout(grid)
        self.keyboard = KeyboardView(interactive=False, compact=True)
        self.keyboard.setMinimumHeight(140)
        prev.add(self.keyboard)
        right.addWidget(prev)

        perf = Card(tr("sync.metrics"))
        mg = QGridLayout()
        mg.setHorizontalSpacing(18)
        mg.setVerticalSpacing(14)
        self.m = {
            "cap": MetricTile(tr("metric.capture_fps")),
            "ana": MetricTile(tr("metric.analysis_ms")),
            "lat": MetricTile(tr("metric.pipeline_ms")),
            "hid": MetricTile(tr("metric.hid_rate")),
            "hidms": MetricTile(tr("metric.hid_ms")),
            "dup": MetricTile(tr("metric.skipped")),
            "cuts": MetricTile(tr("metric.scene_cuts")),
            "cpu": MetricTile(tr("metric.engine_cpu")),
            "app": MetricTile(tr("metric.app_cpu")),
        }
        for i, w in enumerate(self.m.values()):
            mg.addWidget(w, i // 3, i % 3)
        perf.add_layout(mg)
        self.backend_info = label("", caption=True, wrap=True)
        perf.add(self.backend_info)
        right.addWidget(perf)
        right.addStretch(1)
        cols.addLayout(right, 4)
        self.content.addLayout(cols)

        self._load_monitors()
        self._load_from_state()

    # ------------------------------------------------------------ loading
    def _load_monitors(self) -> None:
        self._loading = True
        try:
            self.monitor.clear()
            self.monitor.addItem(tr("sync.primary_monitor"), None)
            for m in enumerate_monitors():
                extra = f" · {m.refresh_hz:.0f} Hz" if m.refresh_hz else ""
                hdr = " · HDR" if m.hdr_enabled else ""
                prim = f" ({tr('sync.primary')})" if m.primary else ""
                self.monitor.addItem(f"{m.index + 1}: {m.name} — {m.width}×{m.height}{extra}{hdr}{prim}", m.id)
            idx = max(0, self.monitor.findData(self.ctx.settings.monitor_id))
            self.monitor.setCurrentIndex(idx)
        finally:
            self._loading = False

    def _load_from_state(self) -> None:
        self._loading = True
        try:
            self._sp = self.controller.state.sync
            a, t, o = self._sp.analysis, self._sp.transition, self._sp.output
            s = self.ctx.settings
            self.mode.set_current(a.mode.value)
            self.mode_desc.setText(tr(f"algo.{a.mode.value}.desc"))
            self.weighting.setCurrentIndex(max(0, self.weighting.findData(a.spatial_weighting.value)))
            self.letterbox.setChecked(a.ignore_letterbox)
            self.subtitle.setChecked(a.subtitle_guard)
            self.cut_fast.setChecked(t.scene_cut_fast)
            self.flash_guard.setChecked(t.flash_guard)
            self.s_sensitivity.setValue(t.sensitivity)
            self.s_speed.setValue(t.transition_speed)
            self.s_smooth.setValue(t.smoothing)
            self.s_bright.setValue(o.brightness)
            self.s_sat.setValue(o.saturation)
            self.s_black.setValue(int(round(a.black_level * 100)))
            self.s_mindiff.setValue(t.min_color_difference)
            self.s_rate.setValue(int(round(s.update_hz)))
            self.perf.set_current(self._sp.performance)
            self.perf_hint.setText(tr(f"perf.{self._sp.performance}.desc"))
            self.backend.setCurrentIndex(max(0, self.backend.findData(s.capture_backend)))
            for sp, v in zip(self.region_spins, s.region):
                sp.blockSignals(True)
                sp.setValue(v * 100)
                sp.blockSignals(False)
        finally:
            self._loading = False

    def on_shown(self) -> None:
        self._load_from_state()

    # ------------------------------------------------------------- changes
    def _build(self) -> SyncProfile:
        a = AnalysisSettings.from_dict(self._sp.analysis.to_dict())
        t = TransitionSettings.from_dict(self._sp.transition.to_dict())
        o = OutputSettings.from_dict(self._sp.output.to_dict())
        a.mode = SyncMode(self.mode.current() or a.mode.value)
        a.spatial_weighting = SpatialWeighting(self.weighting.currentData() or "uniform")
        a.ignore_letterbox = self.letterbox.isChecked()
        a.subtitle_guard = self.subtitle.isChecked()
        a.black_level = self.s_black.value() / 100.0
        t.scene_cut_fast = self.cut_fast.isChecked()
        t.flash_guard = self.flash_guard.isChecked()
        t.sensitivity = self.s_sensitivity.value()
        t.transition_speed = self.s_speed.value()
        t.smoothing = self.s_smooth.value()
        t.min_color_difference = self.s_mindiff.value()
        o.brightness = self.s_bright.value()
        o.saturation = self.s_sat.value()
        return SyncProfile(a, t, o, self.perf.current() or self._sp.performance)

    def _changed(self, *_a) -> None:
        if self._loading:
            return
        self._sp = self._build()
        self.mode_desc.setText(tr(f"algo.{self._sp.analysis.mode.value}.desc"))
        self.perf_hint.setText(tr(f"perf.{self._sp.performance}.desc"))
        self.controller.update_sync(self._sp)

    def _mode_changed(self, _k: str) -> None:
        self._changed()

    def _perf_changed(self, _k: str) -> None:
        self._changed()

    def _rate_changed(self, v: int) -> None:
        if self._loading:
            return
        self.ctx.save_settings(update_hz=float(v))
        self.controller.apply_device_settings()

    def _monitor_changed(self, _i: int) -> None:
        if self._loading:
            return
        self.ctx.save_settings(monitor_id=self.monitor.currentData())
        self.controller.apply_capture_settings()

    def _backend_changed(self, _i: int) -> None:
        if self._loading:
            return
        self.ctx.save_settings(capture_backend=self.backend.currentData())
        self.controller.apply_capture_settings()

    def _region_changed(self, *_a) -> None:
        if self._loading:
            return
        vals = [sp.value() / 100.0 for sp in self.region_spins]
        x, y, w, h = vals
        w = max(0.05, min(w, 1.0 - x))
        h = max(0.05, min(h, 1.0 - y))
        self.ctx.save_settings(region=[x, y, w, h])
        self.controller.apply_capture_settings()

    def _region_full(self) -> None:
        self._loading = True
        for sp, v in zip(self.region_spins, (0, 0, 100, 100)):
            sp.setValue(v)
        self._loading = False
        self._region_changed()

    def _reset_defaults(self) -> None:
        self._sp = SyncProfile(AnalysisSettings(mode=self._sp.analysis.mode), TransitionSettings(), OutputSettings(), self._sp.performance)
        self.controller.update_sync(self._sp)
        self._load_from_state()

    def _toggle(self) -> None:
        if self.controller.state.mode == Mode.SCREEN_SYNC:
            self.controller.stop_sync()
        else:
            self.controller.start_sync(self._build())

    # -------------------------------------------------------------- update
    def update_snapshot(self, snap: AppSnapshot) -> None:
        running = snap.mode == Mode.SCREEN_SYNC
        self.start_btn.setText(tr("sync.stop") if running else tr("sync.start"))
        s = snap.sync
        frame, crop = self.controller.sync_preview()
        self.preview.set_frame(frame if running else None, crop, self._sp.analysis.mode == SyncMode.SPATIAL)
        self.keyboard.set_colors(snap.intended)
        self.keyboard.set_badge(*keyboard_badge(snap))
        d = snap.device
        if s is None or not running:
            for c in self.target_chips + self.output_chips + self.palette_chips:
                c.set_color(None)
            for k in self.m.values():
                k.set_value("—")
            self.m["app"].set_value(f"{snap.cpu_percent:.1f}%")
            self.backend_info.setText(tr("sync.not_running"))
            self.banner.show_message("")
            return
        for i in range(4):
            self.target_chips[i].set_color(s.targets[i] if s.targets else None)
            self.output_chips[i].set_color(snap.intended[i] if snap.intended else None)
        for i, chip in enumerate(self.palette_chips):
            chip.set_color(s.palette[i][0] if i < len(s.palette) else None)
            chip.setToolTip(f"{int(s.palette[i][1] * 100)}%" if i < len(s.palette) else "")
        self.m["cap"].set_value(f"{s.capture_fps:.1f}")
        self.m["ana"].set_value(f"{s.analysis_ms:.1f}")
        self.m["lat"].set_value(f"{s.pipeline_ms:.1f}")
        self.m["hid"].set_value(f"{d.updates_per_sec:.1f}")
        self.m["hidms"].set_value(f"{d.write_latency_ms:.2f}")
        self.m["dup"].set_value(f"{d.duplicates_skipped + s.deadband_suppressed}")
        self.m["cuts"].set_value(f"{s.scene_cuts}")
        self.m["cpu"].set_value(f"{s.cpu_percent:.1f}%")
        self.m["app"].set_value(f"{snap.cpu_percent:.1f}%")
        algo = algo_name(s.mode_label) if s.mode_label else ""
        self.backend_info.setText(tr("sync.backend_info", backend=s.backend or "—", monitor=s.monitor or "—", algo=algo or "—",
                                     static=s.frames_static, nochange=s.frames_no_change))
        if s.state == "backoff" or s.error_code:
            self.banner.show_message(tr(f"capture_error.{s.error_code}", default=s.last_error, retry=f"{s.retry_in_s:.0f}")
                                     if s.error_code else s.last_error, "danger")
        elif s.warning == "black_frames":
            self.banner.show_message(tr("sync.warn_black"), "warning")
        elif s.warning == "hdr":
            self.banner.show_message(tr("sync.warn_hdr"), "info")
        elif s.warning == "monitor_fallback":
            self.banner.show_message(tr("sync.warn_monitor"), "warning")
        else:
            self.banner.show_message("")
