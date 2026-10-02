"""A small in-process sliding-window counter, keyed by string.

WHY IT IS ITS OWN MODULE
    `routers/demo_request.py` has a limiter written inside it and
    `middleware/rate_limit.py` has another, keyed on (firm, path prefix) for the AI
    endpoints. Neither is reusable by a caller that has no firm and wants one
    number per address, and a third private copy inside the payment webhook would
    be the thing this repository keeps having to record. This is the small,
    bounded, lock-guarded version of exactly that, with nothing else in it.

HONESTY ABOUT SCOPE
    In-process, which is what the API is: one Render service, one gunicorn worker.
    If that ever becomes several processes each one enforces its own window, so
    the effective limit is N times this. The same caveat `demo_request` carries,
    written down here rather than left to be discovered.

BOUNDED MEMORY
    A caller rotating source addresses must not be able to grow the table without
    limit, so it is capped and the COLDEST keys are dropped when it fills. Dropping
    a cold key forgets an address that has been quiet, which can only let it
    through again early; it cannot refuse anyone.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional


class SlidingWindowLimiter:
    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        max_keys: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_events < 1 or window_seconds <= 0 or max_keys < 1:
            raise ValueError("a limiter needs a positive budget, window and key cap")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._events: Dict[str, Deque[float]] = {}

    def hit(self, key: str) -> bool:
        """Record one event for `key`. True if it is within budget, False if not.

        A refused event is NOT recorded: counting it would let a caller who keeps
        hammering extend their own lockout for ever, which turns a rate limit
        into a ban.
        """
        return self.hit_or_wait(key) is None

    def hit_or_wait(self, key: str) -> Optional[int]:
        """`hit`, but a refusal says how long to wait.

        None means the event was recorded and is within budget. A number is the
        whole seconds (never below 1, rounded UP so the caller is not told to come
        back a moment too early) until the OLDEST event in the window ages out and
        a place opens: exactly what `Retry-After` should carry. The same rules as
        `hit` otherwise, and a refused event is likewise not recorded.
        """
        now = self._clock()
        with self._lock:
            bucket = self._events.get(key)
            if bucket is None:
                if len(self._events) >= self.max_keys:
                    self._drop_coldest()
                bucket = self._events[key] = deque()
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_events:
                return max(1, math.ceil(bucket[0] + self.window_seconds - now))
            bucket.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def _drop_coldest(self) -> None:
        # Called with the lock held. A quarter at a time, so a full table is
        # sorted once per quarter-table of new keys and not once per request.
        ranked = sorted(self._events, key=lambda k: self._events[k][-1] if self._events[k] else 0.0)
        for stale in ranked[: max(1, self.max_keys // 4)]:
            self._events.pop(stale, None)
