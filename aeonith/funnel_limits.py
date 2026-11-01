"""Small, thread-safe admission boundary for an optional public Funnel.

All decisions are **process-local** and use monotonic time. This module has
no database, credentials, network calls, request bodies or client identifiers.
It does not implement distributed limits and makes no spending guarantees for
other services. The local model endpoint remains the only inference target.

Call ``auth_attempt_allowed`` only after a denied bearer token, then
``record_auth_failure`` for permitted failures. After successful auth but
before reading a manuscript body, call ``begin_review`` and always release
the returned reservation in ``finally``. A reservation counts toward the
hourly review allowance even if parsing or the model subsequently fails.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock


_AUTH_WINDOW_SECONDS = 60
_REVIEW_WINDOW_SECONDS = 3600


class Reservation:
    """Idempotent slot release; never stores the caller's identity or text."""

    def __init__(self, owner: LocalAdmission) -> None:
        self._owner = owner
        self._lock = Lock()
        self._released = False

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
            self._owner._finish_review()

    def __enter__(self) -> Reservation:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


class LocalAdmission:
    """Bound public review concurrency and hourly/failed-auth request counts.

    The default capacity protects a single already-owned local model. All
    timestamps are stored in fixed-size deques. Shared lock operations are
    short and never include network I/O, JSON parsing or model invocation.
    """

    def __init__(
        self,
        *,
        max_inflight: int = 2,
        max_reviews_per_hour: int = 30,
        max_auth_failures_per_minute: int = 20,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value, upper in (
            ("max_inflight", max_inflight, 16),
            ("max_reviews_per_hour", max_reviews_per_hour, 10000),
            ("max_auth_failures_per_minute", max_auth_failures_per_minute, 1000),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be a positive bounded integer")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock
        self._max_inflight = max_inflight
        self._max_reviews_per_hour = max_reviews_per_hour
        self._max_auth_failures_per_minute = max_auth_failures_per_minute
        self._inflight = 0
        self._recent_reviews: deque[float] = deque(maxlen=max_reviews_per_hour)
        self._recent_auth_failures: deque[float] = deque(maxlen=max_auth_failures_per_minute)
        self._lock = Lock()

    @staticmethod
    def _prune(stamps: deque[float], window: int, now: float) -> None:
        while stamps and now - stamps[0] >= window:
            stamps.popleft()

    @staticmethod
    def _retry_after(stamps: deque[float], window: int, now: float) -> int:
        return max(1, min(window, math.ceil(window - (now - stamps[0]))))

    def auth_attempt_allowed(self) -> tuple[bool, int]:
        """Whether another credential attempt is allowed (and retry seconds)."""
        with self._lock:
            now = self._clock()
            self._prune(self._recent_auth_failures, _AUTH_WINDOW_SECONDS, now)
            if len(self._recent_auth_failures) >= self._max_auth_failures_per_minute:
                return False, self._retry_after(self._recent_auth_failures, _AUTH_WINDOW_SECONDS, now)
            return True, 0

    def record_auth_failure(self) -> None:
        """Count an invalid bearer token; denied floods cannot refresh a cap."""
        with self._lock:
            now = self._clock()
            self._prune(self._recent_auth_failures, _AUTH_WINDOW_SECONDS, now)
            if len(self._recent_auth_failures) < self._max_auth_failures_per_minute:
                self._recent_auth_failures.append(now)

    def begin_review(self) -> tuple[Reservation | None, int]:
        """Reserve a bounded in-flight slot and hourly allowance, atomically.

        A caller gets either a reservation and zero delay, or ``None`` plus a
        positive, integer Retry-After recommendation. Denied attempts consume
        no hourly allowance. Releases restore only capacity, not the quota.
        """
        with self._lock:
            if self._inflight >= self._max_inflight:
                return None, 1
            now = self._clock()
            self._prune(self._recent_reviews, _REVIEW_WINDOW_SECONDS, now)
            if len(self._recent_reviews) >= self._max_reviews_per_hour:
                return None, self._retry_after(self._recent_reviews, _REVIEW_WINDOW_SECONDS, now)
            self._inflight += 1
            self._recent_reviews.append(now)
            return Reservation(self), 0

    def _finish_review(self) -> None:
        with self._lock:
            if self._inflight <= 0:
                raise RuntimeError("review release without a reservation")
            self._inflight -= 1
