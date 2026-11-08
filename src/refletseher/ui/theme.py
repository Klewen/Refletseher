"""Design tokens and the Qt style sheet."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    name: str
    bg: str
    sidebar: str
    surface: str
    elevated: str
    hover: str
    border: str
    text: str
    text2: str
    muted: str
    accent: str
    accent2: str
    accent_text: str
    success: str
    warning: str
    danger: str
    info: str
    key_cap: str
    chassis: str


DARK = Tokens(
    name="dark",
    bg="#0D0E12",
    sidebar="#101116",
    surface="#15171D",
    elevated="#1B1E26",
    hover="#232733",
    border="#262A35",
    text="#ECEEF3",
    text2="#A1A7B4",
    muted="#6A7181",
    accent="#7C5CFF",
    accent2="#22D3EE",
    accent_text="#FFFFFF",
    success="#34D399",
    warning="#FBBF24",
    danger="#F87171",
    info="#60A5FA",
    key_cap="#17191F",
    chassis="#0A0B0E",
)

LIGHT = Tokens(
    name="light",
    bg="#F3F4F7",
    sidebar="#ECEEF2",
    surface="#FFFFFF",
    elevated="#F8F9FB",
    hover="#EEF0F5",
    border="#DDE1E8",
    text="#13151A",
    text2="#545B69",
    muted="#8A91A0",
    accent="#6A48F5",
    accent2="#0EA5C6",
    accent_text="#FFFFFF",
    success="#059669",
    warning="#B45309",
    danger="#DC2626",
    info="#2563EB",
    key_cap="#2A2D35",
    chassis="#1A1C22",
)

_current = DARK


def tokens() -> Tokens:
    return _current


def icon_font_family() -> str:
    families = set(QFontDatabase.families())
    for fam in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if fam in families:
            return fam
    return ""


def ui_font_family() -> str:
    families = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Inter"):
        if fam in families:
            return fam
    return QApplication.font().family()


class Glyph:
    """Segoe Fluent Icons / MDL2 code points (built into Windows 10/11)."""

    HOME = ""
    MONITOR = ""
    PALETTE = ""
    SPARKLE = ""
    PROFILES = ""
    HARDWARE = ""
    SETTINGS = ""
    PLAY = ""
    PAUSE = ""
    STOP = ""
    POWER = ""
    UNDO = ""
    ADD = ""
    DELETE = ""
    EDIT = ""
    COPY = ""
    IMPORT = ""
    EXPORT = ""
    STAR = ""
    STAR_FILL = ""
    WARNING = ""
    INFO = ""
    CHECK = ""
    REFRESH = ""
    KEYBOARD = ""
    BRIGHTNESS = ""
    FOLDER = ""
    SAVE = ""
    GAME = ""


def apply_theme(app: QApplication, name: str = "dark") -> Tokens:
    global _current
    _current = LIGHT if name == "light" else DARK
    t = _current
    font = QFont(ui_font_family(), 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t.bg))
    pal.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.Text, QColor(t.text))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Button, QColor(t.elevated))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.elevated))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.muted))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t))
    return t


def stylesheet(t: Tokens) -> str:
    icon = icon_font_family()
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t.text}; font-size: 13px; }}
QMainWindow, #Root {{ background: {t.bg}; }}
QToolTip {{ background: {t.elevated}; color: {t.text}; border: 1px solid {t.border}; padding: 6px 8px; border-radius: 6px; }}

#Sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
#BrandTitle {{ font-size: 15px; font-weight: 600; }}
#BrandSub {{ color: {t.muted}; font-size: 11px; }}
#NavButton {{
    text-align: left; padding: 9px 12px; border: none; border-radius: 9px;
    color: {t.text2}; background: transparent; font-size: 13px;
}}
#NavButton:hover {{ background: {t.hover}; color: {t.text}; }}
#NavButton:checked {{ background: {t.elevated}; color: {t.text}; font-weight: 600; }}

#PageTitle {{ font-size: 22px; font-weight: 600; }}
#PageSubtitle {{ color: {t.text2}; font-size: 13px; }}
#SectionTitle {{ font-size: 14px; font-weight: 600; }}
#Caption, QLabel[caption="true"] {{ color: {t.muted}; font-size: 11.5px; }}
QLabel[secondary="true"] {{ color: {t.text2}; }}
#Metric {{ font-size: 20px; font-weight: 600; }}
#MetricLabel {{ color: {t.muted}; font-size: 11px; }}
#Mono {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }}

#Card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
#CardInner {{ background: {t.elevated}; border: 1px solid {t.border}; border-radius: 10px; }}
#Banner {{ border-radius: 10px; padding: 2px; }}
#Banner[level="warning"] {{ background: rgba(251,191,36,0.10); border: 1px solid rgba(251,191,36,0.35); }}
#Banner[level="danger"] {{ background: rgba(248,113,113,0.10); border: 1px solid rgba(248,113,113,0.35); }}
#Banner[level="info"] {{ background: rgba(96,165,250,0.10); border: 1px solid rgba(96,165,250,0.35); }}

QPushButton {{
    background: {t.elevated}; border: 1px solid {t.border}; border-radius: 9px;
    padding: 7px 14px; color: {t.text};
}}
QPushButton:hover {{ background: {t.hover}; }}
QPushButton:pressed {{ background: {t.border}; }}
QPushButton:disabled {{ color: {t.muted}; background: {t.surface}; }}
QPushButton[primary="true"] {{ background: {t.accent}; border: 1px solid {t.accent}; color: {t.accent_text}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {QColor(t.accent).lighter(112).name()}; }}
QPushButton[primary="true"]:disabled {{ background: {t.border}; border-color: {t.border}; color: {t.muted}; }}
QPushButton[danger="true"] {{ color: {t.danger}; }}
QPushButton[ghost="true"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[ghost="true"]:hover {{ background: {t.hover}; }}
QPushButton[icon="true"] {{ font-family: "{icon}"; font-size: 14px; padding: 6px 9px; }}
QPushButton[chip="true"] {{ border-radius: 14px; padding: 5px 12px; }}
QPushButton[chip="true"]:checked {{ background: {t.accent}; border-color: {t.accent}; color: {t.accent_text}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit, QPlainTextEdit, QListWidget, QTextEdit {{
    background: {t.elevated}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 6px 8px; selection-background-color: {t.accent};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {{ border: 1px solid {t.accent}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 0px; height: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t.elevated}; border: 1px solid {t.border}; selection-background-color: {t.hover}; padding: 4px; }}
QListWidget {{ padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; margin: 1px 0; }}
QListWidget::item:selected {{ background: {t.hover}; color: {t.text}; }}
QListWidget::item:hover {{ background: {t.hover}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {t.text}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; border: 2px solid {t.accent};
}}
QSlider::handle:horizontal:hover {{ background: #FFFFFF; }}
QSlider::groove:horizontal:disabled {{ background: {t.border}; }}
QSlider::sub-page:horizontal:disabled {{ background: {t.muted}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t.text2}; padding: 8px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
QCheckBox {{ spacing: 8px; }}
QMenu {{ background: {t.elevated}; border: 1px solid {t.border}; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.hover}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
QMessageBox {{ background: {t.surface}; }}
QDialog {{ background: {t.surface}; }}
"""


def set_dark_title_bar(widget, dark: bool = True) -> None:
    """Windows 11 immersive dark title bar (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass
