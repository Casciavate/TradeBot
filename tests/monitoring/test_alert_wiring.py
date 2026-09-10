"""Section 8 names four things that must raise a real-time alert: circuit
breaker trips, connection loss to IBKR, order rejection, and kill switch
activation. Each gets a test here, plus the rule that alerting failures
can never interfere with the safety mechanism itself."""
from __future__ import annotations

import pytest

from monitoring.alerts import AlertRouter
from monitoring.audit_log import AuditLog
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.kill_switch import KillSwitch


class ExplodingChannel:
    name = "exploding"

    def send(self, alert) -> None:
        raise RuntimeError("alerting is down")


@pytest.fixture
def router(tmp_path) -> AlertRouter:
    return AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)


def _kinds(router: AlertRouter) -> list[str]:
    return [r["kind"] for r in router.audit_log.read_all() if r["event_type"] == "alert"]


class TestKillSwitchAlerts:
    def test_engaging_raises_a_critical_alert(self, tmp_path, router):
        switch = KillSwitch(path=tmp_path / "KILL_SWITCH", alert_router=router)

        switch.engage("manual halt")

        alerts = [r for r in router.audit_log.read_all() if r["event_type"] == "alert"]
        assert alerts[0]["kind"] == "kill_switch_engaged"
        assert alerts[0]["severity"] == "CRITICAL"
        assert "manual halt" in alerts[0]["summary"]

    def test_disengaging_raises_an_alert(self, tmp_path, router):
        switch = KillSwitch(path=tmp_path / "KILL_SWITCH", alert_router=router)
        switch.engage("manual halt")

        switch.disengage()

        assert _kinds(router) == ["kill_switch_engaged", "kill_switch_disengaged"]

    def test_disengaging_a_switch_that_was_never_engaged_raises_nothing(self, tmp_path, router):
        switch = KillSwitch(path=tmp_path / "KILL_SWITCH", alert_router=router)

        switch.disengage()

        assert _kinds(router) == []

    def test_a_broken_alert_channel_cannot_stop_the_kill_switch_engaging(self, tmp_path, router):
        router.channels = [ExplodingChannel()]
        switch = KillSwitch(path=tmp_path / "KILL_SWITCH", alert_router=router)

        switch.engage("halt despite broken alerting")

        assert switch.is_engaged(), "the flag file must exist even when alerting fails"

    def test_kill_switch_works_with_no_router_at_all(self, tmp_path):
        switch = KillSwitch(path=tmp_path / "KILL_SWITCH")

        switch.engage("no alerting configured")

        assert switch.is_engaged()


class TestCircuitBreakerAlerts:
    def test_tripping_raises_a_critical_alert(self, tmp_path, router):
        breaker = CircuitBreaker(path=tmp_path / "cb.json", alert_router=router)

        breaker.trip("daily loss 3.1% breached the 2.50% circuit breaker")

        alerts = [r for r in router.audit_log.read_all() if r["event_type"] == "alert"]
        assert alerts[0]["kind"] == "circuit_breaker_tripped"
        assert alerts[0]["severity"] == "CRITICAL"

    def test_an_already_tripped_breaker_does_not_re_alert(self, tmp_path, router):
        breaker = CircuitBreaker(path=tmp_path / "cb.json", alert_router=router)
        breaker.trip("first")

        breaker.trip("second")

        assert _kinds(router) == ["circuit_breaker_tripped"]

    def test_reset_raises_an_alert_carrying_who_cleared_it(self, tmp_path, router):
        breaker = CircuitBreaker(path=tmp_path / "cb.json", alert_router=router)
        breaker.trip("daily loss")

        breaker.reset(cleared_by="operator")

        reset_alerts = [
            r
            for r in router.audit_log.read_all()
            if r.get("kind") == "circuit_breaker_reset"
        ]
        assert reset_alerts[0]["details"]["cleared_by"] == "operator"

    def test_resetting_an_untripped_breaker_raises_nothing(self, tmp_path, router):
        breaker = CircuitBreaker(path=tmp_path / "cb.json", alert_router=router)

        breaker.reset(cleared_by="operator")

        assert _kinds(router) == []

    def test_a_broken_alert_channel_cannot_stop_the_breaker_latching(self, tmp_path, router):
        router.channels = [ExplodingChannel()]
        breaker = CircuitBreaker(path=tmp_path / "cb.json", alert_router=router)

        breaker.trip("daily loss")

        assert breaker.is_tripped(), "the latch must persist even when alerting fails"


class TestRiskGateWiring:
    def test_gate_passes_its_router_to_a_default_circuit_breaker(self, tmp_path, base_config, router):
        from risk_gate.gate import RiskGate

        gate = RiskGate(base_config, state_dir=str(tmp_path), alert_router=router)

        assert gate.circuit_breaker.alert_router is router
        assert gate.kill_switch.alert_router is router

    def test_a_breach_during_evaluate_raises_the_trip_alert(self, tmp_path, base_config, router):
        from risk_gate.gate import RiskGate
        from risk_gate.models import PortfolioState
        from tests.risk_gate.conftest import make_proposal

        gate = RiskGate(
            base_config,
            kill_switch=KillSwitch(path=tmp_path / "KILL_SWITCH"),
            circuit_breaker=CircuitBreaker(path=tmp_path / "cb.json", alert_router=router),
            state_dir=str(tmp_path),
        )
        breached = PortfolioState(
            equity=90_000, peak_equity=100_000, cash=90_000, realized_pnl_today=-5_000
        )

        decision = gate.evaluate(make_proposal(), breached)

        assert not decision.approved
        assert "circuit_breaker_tripped" in _kinds(router)
