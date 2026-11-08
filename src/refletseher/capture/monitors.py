"""Monitor discovery via Win32 (EnumDisplayMonitors + DisplayConfig).

Gives physical-pixel geometry, DPI scale, refresh rate, friendly name and
the HDR ("advanced colour") state of every active display. Read-only.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from .base import MonitorInfo

log = logging.getLogger(__name__)

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:  # pragma: no cover
        shcore = None
else:  # pragma: no cover
    user32 = shcore = None


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32), ("statusFlags", ctypes.c_uint32)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("scaling", ctypes.c_uint32),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", ctypes.c_uint32),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", ctypes.c_uint32),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", ctypes.c_uint32),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("infoType", ctypes.c_uint32),
        ("id", ctypes.c_uint32),
        ("adapterId", LUID),
        ("union", ctypes.c_uint64 * 6),  # 48-byte union, 8-byte aligned
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DISPLAYCONFIG_DEVICE_INFO_HEADER), ("viewGdiDeviceName", wintypes.WCHAR * 32)]


class DISPLAYCONFIG_TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("flags", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("edidManufactureId", ctypes.c_uint16),
        ("edidProductCodeId", ctypes.c_uint16),
        ("connectorInstance", ctypes.c_uint32),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", ctypes.c_uint32),
        ("colorEncoding", ctypes.c_uint32),
        ("bitsPerColorChannel", ctypes.c_uint32),
    ]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2(ctypes.Structure):
    """Windows 11 24H2+: distinguishes HDR from WCG / Auto Color Management."""

    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", ctypes.c_uint32),
        ("colorEncoding", ctypes.c_uint32),
        ("bitsPerColorChannel", ctypes.c_uint32),
        ("activeColorMode", ctypes.c_uint32),  # 0 SDR, 1 WCG, 2 HDR
    ]


QDC_ONLY_ACTIVE_PATHS = 0x2
GET_SOURCE_NAME, GET_TARGET_NAME, GET_ADVANCED_COLOR_INFO, GET_ADVANCED_COLOR_INFO_2 = 1, 2, 9, 15
ADVANCED_COLOR_MODE_HDR = 2
MONITORINFOF_PRIMARY = 1


def _hdr_state(adapter_id: LUID, target_id: int) -> dict:
    """HDR support/activity of a display target.

    The v1 "advanced colour" bit is also set for wide-colour / Auto Color
    Management on SDR panels (the Katana's built-in panel reports it), so the
    v2 query (bit 4 = highDynamicRangeSupported, activeColorMode) is used when
    the OS offers it."""
    v2 = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2()
    v2.header.type, v2.header.size = GET_ADVANCED_COLOR_INFO_2, ctypes.sizeof(v2)
    v2.header.adapterId, v2.header.id = adapter_id, target_id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(v2.header)) == 0:
        return {"hdr_supported": bool(v2.value & 0x10), "hdr_enabled": v2.activeColorMode == ADVANCED_COLOR_MODE_HDR}
    v1 = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
    v1.header.type, v1.header.size = GET_ADVANCED_COLOR_INFO, ctypes.sizeof(v1)
    v1.header.adapterId, v1.header.id = adapter_id, target_id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(v1.header)) == 0:
        wide_color_enforced = bool(v1.value & 0x4)
        return {"hdr_supported": bool(v1.value & 0x1) and not wide_color_enforced,
                "hdr_enabled": bool(v1.value & 0x2) and not wide_color_enforced}
    return {}


def _display_config() -> dict[str, dict]:
    """GDI device name -> {name, refresh, hdr_supported, hdr_enabled}."""
    out: dict[str, dict] = {}
    if user32 is None:
        return out
    n_paths, n_modes = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), ctypes.byref(n_modes)) != 0:
        return out
    paths = (DISPLAYCONFIG_PATH_INFO * n_paths.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * n_modes.value)()
    if user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths, ctypes.byref(n_modes), modes, None) != 0:
        return out
    for p in paths[: n_paths.value]:
        src = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
        src.header.type, src.header.size = GET_SOURCE_NAME, ctypes.sizeof(src)
        src.header.adapterId, src.header.id = p.sourceInfo.adapterId, p.sourceInfo.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(src.header)) != 0:
            continue
        info: dict = {"name": "", "refresh": 0.0, "hdr_supported": False, "hdr_enabled": False}
        tgt = DISPLAYCONFIG_TARGET_DEVICE_NAME()
        tgt.header.type, tgt.header.size = GET_TARGET_NAME, ctypes.sizeof(tgt)
        tgt.header.adapterId, tgt.header.id = p.targetInfo.adapterId, p.targetInfo.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(tgt.header)) == 0:
            info["name"] = tgt.monitorFriendlyDeviceName
        rr = p.targetInfo.refreshRate
        if rr.Denominator:
            info["refresh"] = rr.Numerator / rr.Denominator
        info.update(_hdr_state(p.targetInfo.adapterId, p.targetInfo.id))
        out[src.viewGdiDeviceName] = info
    return out


_DPI_SET = False


def ensure_dpi_awareness() -> None:
    """Per-monitor-v2 DPI awareness so geometry is in physical pixels.

    Qt already does this when the QApplication starts; calling it again is a
    harmless no-op (the API refuses to change an already-set awareness)."""
    global _DPI_SET
    if _DPI_SET or user32 is None:
        return
    _DPI_SET = True
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:  # pragma: no cover
        try:
            shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def enumerate_monitors() -> list[MonitorInfo]:
    if user32 is None:  # pragma: no cover
        return []
    ensure_dpi_awareness()
    raw: list[tuple[str, RECT, bool, float]] = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)

    def _cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            scale = 1.0
            if shcore is not None:
                dx, dy = ctypes.c_uint(), ctypes.c_uint()
                if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    scale = dx.value / 96.0
            rc = RECT(mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right, mi.rcMonitor.bottom)
            raw.append((mi.szDevice, rc, bool(mi.dwFlags & MONITORINFOF_PRIMARY), scale))
        return True

    try:
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
        cfg = _display_config()
    except Exception:  # pragma: no cover
        log.exception("monitor enumeration failed")
        return []
    raw.sort(key=lambda r: (not r[2], r[1].left, r[1].top))
    monitors = []
    for i, (dev, rc, primary, scale) in enumerate(raw):
        c = cfg.get(dev, {})
        monitors.append(
            MonitorInfo(
                id=dev,
                index=i,
                name=c.get("name") or dev.replace("\\\\.\\", ""),
                x=rc.left,
                y=rc.top,
                width=rc.right - rc.left,
                height=rc.bottom - rc.top,
                primary=primary,
                dpi_scale=scale,
                refresh_hz=round(c.get("refresh", 0.0), 2),
                hdr_supported=c.get("hdr_supported", False),
                hdr_enabled=c.get("hdr_enabled", False),
            )
        )
    return monitors


def find_monitor(monitors: list[MonitorInfo], monitor_id: str | None) -> MonitorInfo | None:
    if not monitors:
        return None
    if monitor_id:
        for m in monitors:
            if m.id == monitor_id:
                return m
    for m in monitors:
        if m.primary:
            return m
    return monitors[0]
