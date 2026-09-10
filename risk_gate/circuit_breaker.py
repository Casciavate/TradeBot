"""Persistent circuit-breaker latch. Once tripped (daily loss or drawdown
limit breached), it stays tripped -- surviving process restarts -- until a
human explicitly calls reset(). A portfolio snapshot recovering above the
threshold on its own must NOT silently clear this.

A trip raises a CRITICAL section-8 alert when an AlertRouter is supplied.
As with the kill switch, the latch is written to disk before the alert is
raised, and alert delivery failures cannot unlatch it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from monitoring.alerts import AlertKind, AlertRouter, AlertSeverity

DEFAULT_STATE_PATH = Path(__file__).parent.parent / "state" / "circuit_breaker.json"


class CircuitBreaker:
    def __init__(
        self,
        path: str | Path = DEFAULT_STATE_PATH,
        alert_router: AlertRouter | None = None,
    ):
        self.path = Path(path)
        self.alert_router = alert_router

    def is_tripped(self) -> bool:
        return self._read() is not None

    def trip(self, reason: str) -> None:
        if self.is_tripped():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tripped_at = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps({"reason": reason, "tripped_at": tripped_at}))
        self._alert(
            AlertKind.CIRCUIT_BREAKER_TRIPPED,
            AlertSeverity.CRITICAL,
            f"Circuit breaker TRIPPED: {reason}",
            {"reason": reason, "tripped_at": tripped_at, "path": str(self.path)},
        )

    def reset(self, cleared_by: str) -> dict | None:
        info = self._read()
        self.path.unlink(missing_ok=True)
        if info is not None:
            self._alert(
                AlertKind.CIRCUIT_BREAKER_RESET,
                AlertSeverity.WARNING,
                f"Circuit breaker reset by {cleared_by} -- trading re-enabled",
                {"cleared_by": cleared_by, "original_trip": info},
            )
        return info

    def info(self) -> dict | None:
        return self._read()

    def _read(self) -> dict | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())

    def _alert(self, kind: AlertKind, severity: AlertSeverity, summary: str, details: dict) -> None:
        if self.alert_router is None:
            return
        self.alert_router.alert(kind, severity, summary, details, dedup_key=str(self.path))
