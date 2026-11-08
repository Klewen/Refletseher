"""Logging: rotating file in %LOCALAPPDATA%, in-memory tail for the GUI."""

from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from logging.handlers import RotatingFileHandler

from .paths import log_dir

_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)-12s %(name)s: %(message)s"


class MemoryHandler(logging.Handler):
    def __init__(self, capacity: int = 800) -> None:
        super().__init__()
        self.records: deque[str] = deque(maxlen=capacity)
        self._lock2 = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # pragma: no cover
            return
        with self._lock2:
            self.records.append(msg)

    def tail(self, n: int = 400) -> list[str]:
        with self._lock2:
            return list(self.records)[-n:]


MEMORY = MemoryHandler()
_configured = False


def setup_logging(debug: bool = False) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter(_FORMAT)
    try:
        fh = RotatingFileHandler(log_dir() / "refletseher.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:  # pragma: no cover
        pass
    MEMORY.setFormatter(fmt)
    root.addHandler(MEMORY)
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logging.getLogger("comtypes").setLevel(logging.WARNING)
    logging.getLogger("dxcam").setLevel(logging.WARNING)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("refletseher").critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("refletseher").error(
            "Unhandled exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_hook
