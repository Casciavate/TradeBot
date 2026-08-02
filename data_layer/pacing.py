"""Client-side enforcement of IBKR's documented historical-data pacing
rules (see docs/LIBRARY_DECISIONS.md): no more than ~60 requests per
rolling 10-minute window, and no identical request repeated within 15
seconds. These are treated as hard limits the code refuses to cross, not
suggestions -- IBKR will otherwise throttle or disconnect the client."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

RequestKey = tuple


class HistoricalDataPacingGuard:
    def __init__(
        self,
        max_requests_per_10_min: int = 60,
        min_seconds_between_identical_requests: float = 15.0,
    ):
        self.max_requests_per_10_min = max_requests_per_10_min
        self.min_seconds_between_identical_requests = min_seconds_between_identical_requests
        self._timestamps: deque[datetime] = deque()
        self._last_request_at: dict[RequestKey, datetime] = {}

    def check(self, request_key: RequestKey, now: datetime | None = None) -> tuple[bool, str | None]:
        now = now or datetime.now(timezone.utc)
        self._prune(now)

        if len(self._timestamps) >= self.max_requests_per_10_min:
            return False, (
                f"would exceed {self.max_requests_per_10_min} historical data requests "
                "per rolling 10-minute window"
            )

        last = self._last_request_at.get(request_key)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < self.min_seconds_between_identical_requests:
                return False, (
                    f"identical request {request_key} repeated after {elapsed:.1f}s "
                    f"(minimum {self.min_seconds_between_identical_requests}s)"
                )

        return True, None

    def record(self, request_key: RequestKey, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._timestamps.append(now)
        self._last_request_at[request_key] = now
        self._prune(now)

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=10)
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
