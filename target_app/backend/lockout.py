"""Failed-attempt counter and lockout (FR-16, FR-18 to FR-20, FR-23 to FR-25).

Counts are kept in memory per key. The caller passes the normalized email.
"""

import math
import time
from typing import Callable

MAX_FAILED_ATTEMPTS = 3
LOCK_SECONDS = 5


class LoginAttemptTracker:
    def __init__(self, max_failures: int = MAX_FAILED_ATTEMPTS,
                 lockout_seconds: float = LOCK_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def _expire(self, email: str, now: float) -> None:
        # FR-23: once a lockout has ended, the count starts again from 0.
        end = self._locked_until.get(email)
        if end is not None and now >= end:
            del self._locked_until[email]
            self._failures.pop(email, None)

    def retry_after(self, email: str) -> int:
        """Whole seconds until the lockout ends, rounded up; 0 when not locked."""
        now = self._clock()
        self._expire(email, now)
        end = self._locked_until.get(email)
        if end is None:
            return 0
        return max(1, math.ceil(end - now))

    def record_failure(self, email: str) -> int:
        """Count a failed login and return the attempts left. 0 starts the lockout."""
        now = self._clock()
        self._expire(email, now)
        count = self._failures.get(email, 0) + 1
        self._failures[email] = count
        left = max(0, self._max_failures - count)
        if left == 0:
            self._locked_until[email] = now + self._lockout_seconds
        return left

    def record_success(self, email: str) -> None:
        self._failures.pop(email, None)
        self._locked_until.pop(email, None)

    def failures(self, email: str) -> int:
        self._expire(email, self._clock())
        return self._failures.get(email, 0)
