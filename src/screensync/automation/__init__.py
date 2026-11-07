"""Rule based profile automation (modular, extendable).

A rule implements :class:`Rule` - ``matches(ctx)`` decides if it is active.
The service evaluates enabled rules by priority and is *edge triggered*:
it applies a profile when a rule becomes active and (optionally) reverts
to the profile that was active before when it stops matching. Manual
profile changes by the user are never overridden until the next edge.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import logging
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from ..core.settings import AutomationRule

log = logging.getLogger(__name__)

PRIORITY = {"process": 100, "fullscreen": 80, "schedule": 50}
# never treat these as "games" in the fullscreen heuristic
FULLSCREEN_EXCLUDE = {
    "explorer.exe", "screensyncrgb.exe", "python.exe", "pythonw.exe", "applicationframehost.exe",
    "searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe", "lockapp.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vlc.exe", "mpc-hc64.exe",
    "potplayermini64.exe", "wmplayer.exe", "video.ui.exe", "microsoft.media.player.exe",
}


@dataclass
class Context:
    now: dt.datetime
    processes: set[str] = field(default_factory=set)  # lower-case exe names
    fullscreen_exe: Optional[str] = None


class Rule(Protocol):
    id: str
    priority: int
    profile_id: str
    revert: bool

    def matches(self, ctx: Context) -> bool: ...


def parse_hhmm(text: str) -> dt.time:
    h, m = text.strip().split(":")
    return dt.time(int(h) % 24, int(m) % 60)


def in_time_range(now: dt.time, start: dt.time, end: dt.time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end  # wraps midnight


@dataclass
class _Adapter:
    rule: AutomationRule

    @property
    def id(self) -> str:
        return self.rule.id

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.rule.kind, 0)

    @property
    def profile_id(self) -> str:
        return self.rule.profile_id

    @property
    def revert(self) -> bool:
        return self.rule.revert

    def matches(self, ctx: Context) -> bool:
        r = self.rule
        if not r.enabled:
            return False
        if r.kind == "process":
            return any(p in ctx.processes for p in r.processes)
        if r.kind == "schedule":
            try:
                return in_time_range(ctx.now.time(), parse_hhmm(r.start), parse_hhmm(r.end))
            except (ValueError, AttributeError):
                return False
        if r.kind == "fullscreen":
            exe = ctx.fullscreen_exe
            return bool(exe) and exe not in FULLSCREEN_EXCLUDE and (not r.processes or exe in r.processes)
        return False


def select_rule(rules: list[Rule], ctx: Context) -> Optional[Rule]:
    active = [r for r in rules if r.matches(ctx)]
    if not active:
        return None
    return max(active, key=lambda r: r.priority)


def running_processes() -> set[str]:
    try:
        import psutil

        return {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
    except Exception:  # pragma: no cover
        return set()


def fullscreen_foreground_exe() -> Optional[str]:
    """Exe name of the foreground window if it covers its whole monitor."""
    if sys.platform != "win32":  # pragma: no cover
        return None
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    hmon = user32.MonitorFromWindow(hwnd, 2)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    m = mi.rcMonitor
    if not (rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil

        return psutil.Process(pid.value).name().lower()
    except Exception:
        return None


class AutomationService:
    def __init__(
        self,
        rules_fn: Callable[[], list[AutomationRule]],
        apply_fn: Callable[[str, str], None],
        revert_fn: Callable[[str], None],
        interval: float = 3.0,
        context_fn: Callable[[], Context] | None = None,
    ) -> None:
        self._rules_fn = rules_fn
        self._apply = apply_fn
        self._revert = revert_fn
        self.interval = interval
        self._context_fn = context_fn or self._default_context
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.active_rule: Optional[str] = None
        self.last_error = ""

    @staticmethod
    def _default_context() -> Context:
        return Context(dt.datetime.now(), running_processes(), fullscreen_foreground_exe())

    def evaluate_once(self) -> Optional[str]:
        rules: list[Rule] = [_Adapter(r) for r in self._rules_fn()]
        ctx = self._context_fn()
        chosen = select_rule(rules, ctx)
        new_id = chosen.id if chosen else None
        if new_id != self.active_rule:
            old = next((r for r in rules if r.id == self.active_rule), None)
            self.active_rule = new_id
            if chosen is not None:
                log.info("Automation rule %s active -> profile %s", chosen.id, chosen.profile_id)
                self._apply(chosen.profile_id, chosen.id)
            elif old is None or old.revert:
                log.info("Automation rule ended -> revert")
                self._revert(old.id if old else "")
        return new_id

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Automation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.evaluate_once()
                self.last_error = ""
            except Exception as exc:  # pragma: no cover
                log.exception("automation evaluation failed")
                self.last_error = str(exc)
            self._stop.wait(self.interval)
