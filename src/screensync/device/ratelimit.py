"""Rate limiting primitives for HID traffic (clock injectable for tests)."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

Clock = Callable[[], float]


class TokenBucket:
    """Classic token bucket: ``rate`` tokens/s, at most ``capacity`` stored."""

    def __init__(self, rate: float, capacity: float, clock: Clock = time.perf_counter) -> None:
        if rate <= 0 or capacity < 1:
            raise ValueError("rate must be > 0 and capacity >= 1")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def try_acquire(self, n: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def wait_time(self, n: float = 1.0) -> float:
        """Seconds until ``n`` tokens are available (0 if available now)."""
        self._refill()
        if self._tokens >= n:
            return 0.0
        return (n - self._tokens) / self.rate

    def acquire(self, n: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> float:
        """Block until ``n`` tokens are available. Returns time slept."""
        if n > self.capacity:
            raise ValueError("cannot acquire more tokens than the bucket capacity")
        slept = 0.0
        while True:
            w = self.wait_time(n)
            if w <= 0:
                self._tokens -= n
                return slept
            sleep(w)
            slept += w


class MinInterval:
    """Allows an event at most once every ``interval`` seconds."""

    def __init__(self, interval: float, clock: Clock = time.perf_counter) -> None:
        self.interval = max(0.0, float(interval))
        self._clock = clock
        self._last: float | None = None

    def remaining(self) -> float:
        if self._last is None:
            return 0.0
        return max(0.0, self._last + self.interval - self._clock())

    def mark(self) -> None:
        self._last = self._clock()

    def reset(self) -> None:
        self._last = None


class RateMeter:
    """Events per second over a sliding window."""

    def __init__(self, window: float = 2.0, clock: Clock = time.perf_counter) -> None:
        self.window = window
        self._clock = clock
        self._events: deque[float] = deque()

    def tick(self, n: int = 1) -> None:
        now = self._clock()
        for _ in range(n):
            self._events.append(now)
        self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def rate(self) -> float:
        now = self._clock()
        self._trim(now)
        return len(self._events) / self.window


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff: 1, 2, 4, 8, 16, 30, 30 ... seconds."""
    if attempt <= 0:
        return 0.0
    return min(cap, base * (2 ** (attempt - 1)))
