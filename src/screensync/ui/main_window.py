"""Main window: sidebar navigation, pages, tray icon, system events."""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..core.controller import AppController, Mode
from ..i18n import tr
from .base import UiContext, device_status, mode_text
from .icon import app_icon, render_icon
from .pages.dashboard import DashboardPage
from .pages.effects import EffectsPage
from .pages.hardware import HardwarePage
from .pages.profiles import ProfilesPage
from .pages.rgb_studio import RgbStudioPage
from .pages.screen_sync import ScreenSyncPage
from .pages.settings import SettingsPage
from .theme import Glyph, icon_font_family, set_dark_title_bar, tokens
from .widgets.common import StatusPill, label

log = logging.getLogger(__name__)

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
WM_WTSSESSION_CHANGE = 0x02B1


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


# {6FE69556-704A-47A0-8F24-C28D936FDA47}
GUID_CONSOLE_DISPLAY_STATE = _GUID(0x6FE69556, 0x704A, 0x47A0, (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", _GUID), ("DataLength", ctypes.c_uint32), ("Data", ctypes.c_ubyte * 1)]
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

NAV = [
    ("dashboard", Glyph.HOME, "nav.dashboard"),
    ("sync", Glyph.MONITOR, "nav.sync"),
    ("studio", Glyph.PALETTE, "nav.studio"),
    ("effects", Glyph.SPARKLE, "nav.effects"),
    ("profiles", Glyph.PROFILES, "nav.profiles"),
    ("hardware", Glyph.KEYBOARD, "nav.hardware"),
    ("settings", Glyph.SETTINGS, "nav.settings"),
]


class NavButton(QPushButton):
    def __init__(self, glyph: str, text: str) -> None:
        super().__init__()
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(12)
        fam = icon_font_family()
        self.icon_label = QLabel(glyph if fam else "•")
        self.icon_label.setStyleSheet(f'font-family: "{fam}"; font-size: 16px; background: transparent;')
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text_label = QLabel(text)
        self.text_label.setStyleSheet("background: transparent;")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.icon_label)
        lay.addWidget(self.text_label, 1)
        self.setMinimumHeight(40)
        self.toggled.connect(self._restyle)
        self._restyle(False)

    def _restyle(self, on: bool) -> None:
        t = tokens()
        color = t.text if on else t.text2
        weight = 600 if on else 400
        fam = icon_font_family()
        self.icon_label.setStyleSheet(f'font-family: "{fam}"; font-size: 16px; background: transparent; color: {t.accent if on else t.text2};')
        self.text_label.setStyleSheet(f"background: transparent; color: {color}; font-weight: {weight};")


class Toast(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, level: str = "info") -> None:
        t = tokens()
        color = {"success": t.success, "warning": t.warning, "danger": t.danger}.get(level, t.info)
        self.setStyleSheet(
            f"background: {t.elevated}; color: {t.text}; border: 1px solid {t.border}; border-left: 3px solid {color};"
            "border-radius: 10px; padding: 10px 14px;"
        )
        self.setText(text)
        self.setFixedWidth(360)
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 24)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(3200)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setDuration(400)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self) -> None:
        try:
            self._anim.finished.disconnect(self._hide_once)
        except (RuntimeError, TypeError):
            pass
        if self._fx.opacity() < 0.05:
            self.hide()


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self.ctx = UiContext(controller)
        self._quitting = False
        self._shutdown_done = False
        self._tray_hint_shown = False
        self.setWindowTitle("ScreenSync RGB")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1120, 720)

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 16)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(render_icon(36))
        brand.addWidget(logo)
        bcol = QVBoxLayout()
        bcol.setSpacing(0)
        bcol.addWidget(label("ScreenSync RGB", "BrandTitle"))
        bcol.addWidget(label("MSI MS-1565 · 4-Zone", "BrandSub"))
        brand.addLayout(bcol, 1)
        sv.addLayout(brand)
        sv.addSpacing(18)

        self.stack = QStackedWidget()
        self.pages = {
            "dashboard": DashboardPage(self.ctx),
            "sync": ScreenSyncPage(self.ctx),
            "studio": RgbStudioPage(self.ctx),
            "effects": EffectsPage(self.ctx),
            "profiles": ProfilesPage(self.ctx),
            "hardware": HardwarePage(self.ctx),
            "settings": SettingsPage(self.ctx),
        }
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, NavButton] = {}
        for key, glyph, text_key in NAV:
            b = NavButton(glyph, tr(text_key))
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            sv.addWidget(b)
            self.stack.addWidget(self.pages[key])
        sv.addStretch(1)
        self.side_mode = label("", caption=True, wrap=True)
        sv.addWidget(self.side_mode)
        self.side_pill = StatusPill()
        sv.addWidget(self.side_pill)

        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.toast = Toast(root)

        self.ctx.navigate.connect(self._navigate)
        self.ctx.notify.connect(self.toast.show_message)
        self.ctx.profilesChanged.connect(self._build_tray_menu)
        self.ctx.settingsChanged.connect(self._build_tray_menu)

        self._setup_tray()
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(33)
        self.ui_timer.timeout.connect(self._tick_ui)
        self.ui_timer.start()
        self.bg_timer = QTimer(self)
        self.bg_timer.setInterval(2000)
        self.bg_timer.timeout.connect(self._tick_background)
        self.bg_timer.start()

        self._register_session_notifications()
        self._restore_geometry()
        self.show_page("dashboard")

    # ------------------------------------------------------------ pages
    def show_page(self, key: str) -> None:
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.nav_buttons[key].setChecked(True)
        page.on_shown()
        self._tick_ui()

    def _navigate(self, key: str, arg: object) -> None:
        self.show_page(key)
        if key == "studio" and isinstance(arg, int):
            self.pages["studio"].select_zone(arg)

    def _tick_ui(self) -> None:
        if not self.isVisible() or self.isMinimized():
            return
        try:
            snap = self.controller.snapshot()
        except Exception:  # pragma: no cover
            log.exception("snapshot failed")
            return
        page = self.stack.currentWidget()
        try:
            page.update_snapshot(snap)
        except Exception:  # pragma: no cover - a page bug must not kill the timer
            log.exception("page update failed")
        text, level = device_status(snap.device, snap.simulation_backend)
        self.side_pill.set_status(text, level)
        self.side_mode.setText(mode_text(snap))

    def _tick_background(self) -> None:
        try:
            actions = self.controller.watchdog()
            if actions:
                self.ctx.notify.emit(tr("recovery.restarted", what=", ".join(actions)), "warning")
            snap = self.controller.snapshot()
            self._update_tray(snap)
        except Exception:  # pragma: no cover
            log.exception("background tick failed")

    # ------------------------------------------------------------- tray
    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("ScreenSync RGB")
        self.tray.activated.connect(self._tray_activated)
        self._tray_state = ""
        self._build_tray_menu()
        self.tray.show()

    def _build_tray_menu(self) -> None:
        menu = QMenu()
        menu.addAction(tr("tray.show"), self.bring_to_front)
        self.tray_sync = menu.addAction(tr("sync.start"), self.controller.toggle_sync)
        self.tray_power = menu.addAction(tr("rgb.turn_off"), lambda: self.controller.set_power(not self.controller.state.power))
        prof_menu = menu.addMenu(tr("tray.profiles"))
        group = QActionGroup(prof_menu)
        recent = [self.controller.profiles.get(p) for p in self.ctx.settings.recent_profiles]
        shown = set()
        for p in [r for r in recent if r][:5] + sorted(self.controller.profiles.list(), key=lambda p: p.name.lower()):
            if p.id in shown:
                continue
            shown.add(p.id)
            act = QAction(p.name, prof_menu)
            act.triggered.connect(lambda _=False, pid=p.id: (self.controller.apply_profile(pid), self.ctx.settingsChanged.emit()))
            group.addAction(act)
            prof_menu.addAction(act)
            if len(shown) == 5 and recent:
                prof_menu.addSeparator()
        menu.addSeparator()
        menu.addAction(tr("tray.quit"), self.quit_app)
        old = self.tray.contextMenu()
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        if old is not None:
            old.deleteLater()

    def _update_tray(self, snap) -> None:
        running = snap.mode == Mode.SCREEN_SYNC
        self.tray_sync.setText(tr("sync.stop") if running else tr("sync.start"))
        self.tray_power.setText(tr("rgb.turn_off") if snap.power else tr("rgb.turn_on"))
        state = "sync" if running else ("off" if not snap.power else "normal")
        if state != self._tray_state:
            self._tray_state = state
            self.tray.setIcon(app_icon(state))
        dev, _ = device_status(snap.device, snap.simulation_backend)
        self.tray.setToolTip(f"ScreenSync RGB\n{mode_text(snap)}\n{dev}"[:127])

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.bring_to_front()

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------- lifecycle
    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        set_dark_title_bar(self, tokens().name == "dark")

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        if not self._quitting and self.ctx.settings.close_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("ScreenSync RGB", tr("tray.still_running"), app_icon(), 3500)
            return
        self._save_geometry()
        e.accept()
        self.quit_app()

    def quit_app(self) -> None:
        self._quitting = True
        self._save_geometry()
        self.shutdown()
        QApplication.quit()

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self.ui_timer.stop()
        self.bg_timer.stop()
        try:
            self.controller.shutdown()
        except Exception:  # pragma: no cover
            log.exception("shutdown failed")
        self.tray.hide()

    def _save_geometry(self) -> None:
        try:
            self.ctx.controller.settings_store.update(window_geometry=bytes(self.saveGeometry().toBase64()).decode())
        except Exception:  # pragma: no cover
            pass

    def _restore_geometry(self) -> None:
        from PySide6.QtCore import QByteArray

        g = self.ctx.settings.window_geometry
        if g:
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        else:
            self.resize(1320, 860)

    # --------------------------------------------------- system events
    def _register_session_notifications(self) -> None:
        if sys.platform != "win32":
            return
        try:
            ok = ctypes.windll.wtsapi32.WTSRegisterSessionNotification(int(self.winId()), 0)
            log.info("Session change notifications %s", "registered" if ok else "NOT registered")
        except Exception:  # pragma: no cover
            log.warning("WTSRegisterSessionNotification failed", exc_info=True)
        # Modern Standby (S0 Low Power Idle) laptops - like the Katana 15 HX -
        # never send PBT_APMSUSPEND; the console display state is the signal.
        self._display_state: int | None = None
        try:
            user32 = ctypes.windll.user32
            user32.RegisterPowerSettingNotification.restype = ctypes.c_void_p
            self._power_notify = user32.RegisterPowerSettingNotification(
                ctypes.c_void_p(int(self.winId())), ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0
            )
            log.info("Display state notifications %s", "registered" if self._power_notify else "NOT registered")
        except Exception:  # pragma: no cover
            log.warning("RegisterPowerSettingNotification failed", exc_info=True)

    def _on_power_setting(self, lparam: int) -> None:
        setting = POWERBROADCAST_SETTING.from_address(lparam)
        if bytes(setting.PowerSetting) != bytes(GUID_CONSOLE_DISPLAY_STATE) or setting.DataLength < 4:
            return
        state = ctypes.c_uint32.from_address(lparam + POWERBROADCAST_SETTING.Data.offset).value  # 0 off, 1 on, 2 dimmed
        previous, self._display_state = self._display_state, state
        if previous is None or state == 2:
            return  # initial notification after registering / dimming only
        if state == 0 and previous != 0:
            self.controller.on_display_off()
        elif state == 1 and previous == 0:
            self.controller.on_display_on()

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32" and event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_POWERBROADCAST:
                    if msg.wParam == PBT_APMSUSPEND:
                        self.controller.on_suspend()
                    elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                        self.controller.on_resume()
                    elif msg.wParam == PBT_POWERSETTINGCHANGE and msg.lParam:
                        self._on_power_setting(msg.lParam)
                elif msg.message == WM_WTSSESSION_CHANGE:
                    if msg.wParam == WTS_SESSION_LOCK:
                        self.controller.on_session_lock()
                    elif msg.wParam == WTS_SESSION_UNLOCK:
                        self.controller.on_session_unlock()
            except Exception:  # pragma: no cover
                log.debug("native event handling failed", exc_info=True)
        return super().nativeEvent(event_type, message)
