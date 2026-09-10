from __future__ import annotations

import pytest

from execution_layer.health import ConnectionWatchdog
from monitoring.alerts import AlertRouter
from monitoring.audit_log import AuditLog


class FakeIB:
    def __init__(self, connected: bool = True, raises: bool = False):
        self.connected = connected
        self.raises = raises

    def isConnected(self) -> bool:
        if self.raises:
            raise ConnectionResetError("socket closed")
        return self.connected


@pytest.fixture
def router(tmp_path) -> AlertRouter:
    return AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)


def _kinds(router: AlertRouter) -> list[str]:
    return [r["kind"] for r in router.audit_log.read_all() if r["event_type"] == "alert"]


def test_a_healthy_connection_raises_no_alert(router):
    watchdog = ConnectionWatchdog(FakeIB(connected=True), alert_router=router)

    health = watchdog.check()

    assert health.connected
    assert _kinds(router) == []


def test_losing_the_connection_raises_a_critical_alert(router):
    ib = FakeIB(connected=True)
    watchdog = ConnectionWatchdog(ib, alert_router=router)
    watchdog.check()

    ib.connected = False
    health = watchdog.check()

    assert health.just_lost
    alerts = [r for r in router.audit_log.read_all() if r["event_type"] == "alert"]
    assert alerts[0]["kind"] == "broker_connection_lost"
    assert alerts[0]["severity"] == "CRITICAL"


def test_a_connection_that_stays_down_alerts_once_not_every_cycle(router):
    ib = FakeIB(connected=True)
    watchdog = ConnectionWatchdog(ib, alert_router=router)
    watchdog.check()
    ib.connected = False

    for _ in range(5):
        watchdog.check()

    assert _kinds(router).count("broker_connection_lost") == 1


def test_recovery_raises_a_restored_alert(router):
    ib = FakeIB(connected=True)
    watchdog = ConnectionWatchdog(ib, alert_router=router)
    watchdog.check()
    ib.connected = False
    watchdog.check()

    ib.connected = True
    health = watchdog.check()

    assert health.just_restored
    assert _kinds(router) == ["broker_connection_lost", "broker_connection_restored"]


def test_a_client_that_is_already_down_on_the_first_check_alerts(router):
    watchdog = ConnectionWatchdog(FakeIB(connected=False), alert_router=router)

    health = watchdog.check()

    assert health.just_lost
    assert _kinds(router) == ["broker_connection_lost"]


def test_a_client_that_raises_is_treated_as_disconnected(router):
    """An exception asking whether we are connected is not a reason to
    assume the session is healthy."""
    watchdog = ConnectionWatchdog(FakeIB(raises=True), alert_router=router)

    health = watchdog.check()

    assert not health.connected
    assert _kinds(router) == ["broker_connection_lost"]


def test_the_watchdog_never_reconnects_on_its_own():
    """Auto-reconnecting could mask an order whose fate is unknown, so the
    watchdog must expose no reconnect path at all."""
    watchdog = ConnectionWatchdog(FakeIB(connected=False))

    assert not hasattr(watchdog, "reconnect")
    assert not hasattr(watchdog, "connect")


def test_watchdog_works_without_a_router():
    watchdog = ConnectionWatchdog(FakeIB(connected=False))

    assert not watchdog.check().connected
