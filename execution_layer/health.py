"""Broker connection health monitoring (build spec section 8: alert on
connection loss to IBKR).

This is a poller, not an event subscriber: it asks the broker client
whether it is still connected and raises a CRITICAL alert on the
transition connected -> disconnected, plus a WARNING when it comes back.
Only transitions alert, so a connection that stays down for an hour does
not produce an hour of identical alerts.

It never reconnects on its own. A silent auto-reconnect during a
disconnection could mask an order whose fate is unknown; re-establishing
the connection is a deliberate human/operator step followed by a
reconciliation pass.
"""
from __future__ import annotations

from dataclasses import dataclass

from execution_layer.broker_client import BrokerClient
from monitoring.alerts import AlertKind, AlertRouter, AlertSeverity


@dataclass(frozen=True)
class ConnectionHealth:
    connected: bool
    changed: bool

    @property
    def just_lost(self) -> bool:
        return self.changed and not self.connected

    @property
    def just_restored(self) -> bool:
        return self.changed and self.connected


class ConnectionWatchdog:
    def __init__(
        self,
        ib: BrokerClient,
        alert_router: AlertRouter | None = None,
        label: str = "IBKR",
    ):
        self._ib = ib
        self.alert_router = alert_router
        self.label = label
        self._last_connected: bool | None = None

    def check(self) -> ConnectionHealth:
        """Call once per cycle. A client that raises when asked is treated
        as disconnected -- an exception from isConnected() is not a reason
        to assume the session is healthy."""
        try:
            connected = bool(self._ib.isConnected())
        except Exception:  # noqa: BLE001 -- an unreachable client is a disconnected client
            connected = False

        changed = self._last_connected is not None and connected != self._last_connected
        first_check_down = self._last_connected is None and not connected
        self._last_connected = connected

        health = ConnectionHealth(connected=connected, changed=changed or first_check_down)

        if health.just_lost:
            self._alert(
                AlertKind.BROKER_CONNECTION_LOST,
                AlertSeverity.CRITICAL,
                f"{self.label} connection LOST -- order state is now unverified",
                {
                    "label": self.label,
                    "action": "reconcile positions against IBKR before submitting anything further",
                },
            )
        elif health.just_restored:
            self._alert(
                AlertKind.BROKER_CONNECTION_RESTORED,
                AlertSeverity.WARNING,
                f"{self.label} connection restored -- reconcile before trading",
                {"label": self.label},
            )

        return health

    def _alert(self, kind: AlertKind, severity: AlertSeverity, summary: str, details: dict) -> None:
        if self.alert_router is None:
            return
        self.alert_router.alert(kind, severity, summary, details, dedup_key=self.label)
