"""File-based kill switch. Deliberately the dumbest possible mechanism:
existence of a flag file blocks every new order and can be triggered by a
human touching a file, a CLI script, or a circuit breaker trip -- with no
dependency on the rest of the system being alive or responsive.

Engaging and disengaging raise section-8 alerts when an AlertRouter is
supplied, but alerting is strictly optional: a kill switch that could only
work when the alerting stack is healthy would defeat its own purpose. The
file write happens first, and any alert failure is swallowed by the router.
"""
from __future__ import annotations

from pathlib import Path

from monitoring.alerts import AlertKind, AlertRouter, AlertSeverity

DEFAULT_KILL_SWITCH_PATH = Path(__file__).parent.parent / "state" / "KILL_SWITCH"


class KillSwitch:
    def __init__(
        self,
        path: str | Path = DEFAULT_KILL_SWITCH_PATH,
        alert_router: AlertRouter | None = None,
    ):
        self.path = Path(path)
        self.alert_router = alert_router

    def engage(self, reason: str = "") -> None:
        reason = reason or "kill switch engaged"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason)
        self._alert(
            AlertKind.KILL_SWITCH_ENGAGED,
            AlertSeverity.CRITICAL,
            f"Kill switch ENGAGED: {reason}",
            {"path": str(self.path), "reason": reason},
        )

    def disengage(self) -> None:
        was_engaged = self.is_engaged()
        self.path.unlink(missing_ok=True)
        if was_engaged:
            self._alert(
                AlertKind.KILL_SWITCH_DISENGAGED,
                AlertSeverity.WARNING,
                "Kill switch disengaged -- new orders can be submitted again",
                {"path": str(self.path)},
            )

    def is_engaged(self) -> bool:
        return self.path.exists()

    def reason(self) -> str | None:
        if not self.is_engaged():
            return None
        return self.path.read_text()

    def _alert(self, kind: AlertKind, severity: AlertSeverity, summary: str, details: dict) -> None:
        if self.alert_router is None:
            return
        self.alert_router.alert(kind, severity, summary, details, dedup_key=str(self.path))
