"""Sliding-window order rate limiter. Defense in depth against a runaway
strategy/loop submitting far more proposals than any human could review --
independent of whether individual proposals would otherwise pass risk
checks."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone


class RateLimiter:
    def __init__(self, max_per_minute: int, max_per_hour: int):
        if max_per_minute <= 0 or max_per_hour <= 0:
            raise ValueError("rate limits must be positive")
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour
        self._timestamps: deque[datetime] = deque()

    def check(self, now: datetime | None = None) -> tuple[bool, str | None]:
        now = now or datetime.now(timezone.utc)
        self._prune(now)
        minute_count = sum(1 for t in self._timestamps if now - t <= timedelta(minutes=1))
        hour_count = len(self._timestamps)
        if minute_count >= self.max_per_minute:
            return False, f"order rate limit exceeded: {minute_count}/{self.max_per_minute} per minute"
        if hour_count >= self.max_per_hour:
            return False, f"order rate limit exceeded: {hour_count}/{self.max_per_hour} per hour"
        return True, None

    def record(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._timestamps.append(now)
        self._prune(now)

    def hit(self, now: datetime | None = None) -> tuple[bool, str | None]:
        """Records this attempt and reports whether it is within limits.
        Every evaluation attempt counts, whether or not it's ultimately
        approved for other reasons -- this is what stops a runaway loop
        from ever reaching the other checks at high frequency."""
        now = now or datetime.now(timezone.utc)
        self.record(now)
        minute_count = sum(1 for t in self._timestamps if now - t <= timedelta(minutes=1))
        hour_count = len(self._timestamps)
        if minute_count > self.max_per_minute:
            return False, f"order rate limit exceeded: {minute_count}/{self.max_per_minute} per minute"
        if hour_count > self.max_per_hour:
            return False, f"order rate limit exceeded: {hour_count}/{self.max_per_hour} per hour"
        return True, None

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=1)
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
