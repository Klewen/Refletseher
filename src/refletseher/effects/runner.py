"""Background thread that renders a software effect and streams it."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from ..rgb import ZoneColors

log = logging.getLogger(__name__)


class EffectRunner:
    def __init__(self, render: Callable[[float], ZoneColors], sink: Callable[[ZoneColors], None], hz: float = 30.0) -> None:
        self._render = render
        self._sink = sink
        self.hz = hz
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.frames = 0
        self.error = ""
        self._last: ZoneColors | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="EffectRunner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        t0 = time.perf_counter()
        period = 1.0 / max(1.0, self.hz)
        try:
            while not self._stop.is_set():
                start = time.perf_counter()
                colors = self._render(start - t0)
                if colors != self._last:
                    self._last = colors
                    self._sink(colors)
                self.frames += 1
                left = max(0.0, period - (time.perf_counter() - start))
                if left <= 0.06:
                    time.sleep(left)
                else:
                    self._stop.wait(left)
        except Exception as exc:  # pragma: no cover - watchdog restarts
            log.exception("software effect crashed")
            self.error = str(exc)
