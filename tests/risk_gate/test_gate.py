from __future__ import annotations

from monitoring.audit_log import AuditLog
from risk_gate.gate import RiskGate
from risk_gate.models import PortfolioState
from tests.risk_gate.conftest import make_proposal


def make_gate(base_config, kill_switch, circuit_breaker, tmp_path) -> RiskGate:
    return RiskGate(
        config=base_config,
        kill_switch=kill_switch,
        circuit_breaker=circuit_breaker,
        audit_log=AuditLog(tmp_path / "risk_gate_audit.log"),
    )


def test_clean_proposal_is_approved(base_config, flat_portfolio, kill_switch, circuit_breaker, tmp_path):
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    decision = gate.evaluate(make_proposal(quantity=10, estimated_price=500.0), flat_portfolio)
    assert decision.approved
    assert decision.blocked_reasons == ()


def test_kill_switch_blocks_everything(base_config, flat_portfolio, kill_switch, circuit_breaker, tmp_path):
    kill_switch.engage("test halt")
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    decision = gate.evaluate(make_proposal(quantity=1, estimated_price=1.0), flat_portfolio)
    assert not decision.approved
    assert "kill switch" in decision.blocked_reasons[0]


def test_daily_loss_breach_trips_circuit_breaker_and_latches(base_config, kill_switch, circuit_breaker, tmp_path):
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    losing_portfolio = PortfolioState(
        equity=97_000, peak_equity=100_000, cash=97_000, realized_pnl_today=-3_000
    )
    decision = gate.evaluate(make_proposal(), losing_portfolio)
    assert not decision.approved
    assert circuit_breaker.is_tripped()

    # Even if the next snapshot shows equity recovered, the breaker must
    # stay tripped until a human explicitly resets it.
    recovered_portfolio = PortfolioState(equity=100_000, peak_equity=100_000, cash=100_000)
    decision2 = gate.evaluate(make_proposal(proposal_id="p2"), recovered_portfolio)
    assert not decision2.approved
    assert "circuit breaker" in decision2.blocked_reasons[0]

    circuit_breaker.reset(cleared_by="test-operator")
    decision3 = gate.evaluate(make_proposal(proposal_id="p3"), recovered_portfolio)
    assert decision3.approved


def test_drawdown_breach_trips_circuit_breaker(base_config, kill_switch, circuit_breaker, tmp_path):
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    drawn_down_portfolio = PortfolioState(equity=85_000, peak_equity=100_000, cash=85_000)
    decision = gate.evaluate(make_proposal(), drawn_down_portfolio)
    assert not decision.approved
    assert circuit_breaker.is_tripped()


def test_rate_limit_enforced_across_many_rapid_proposals(base_config, flat_portfolio, kill_switch, circuit_breaker, tmp_path):
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    decisions = [
        gate.evaluate(make_proposal(proposal_id=f"flood-{i}", quantity=1, estimated_price=1.0), flat_portfolio)
        for i in range(50)
    ]
    approved = [d for d in decisions if d.approved]
    blocked = [d for d in decisions if not d.approved]
    assert len(approved) == base_config.risk_limits.max_orders_per_minute
    assert len(blocked) == 50 - base_config.risk_limits.max_orders_per_minute
    assert all("rate limit" in b.blocked_reasons[0] for b in blocked)


def test_every_decision_is_audit_logged(base_config, flat_portfolio, kill_switch, circuit_breaker, tmp_path):
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    gate.evaluate(make_proposal(proposal_id="audited-1"), flat_portfolio)
    records = gate.audit_log.read_all()
    assert len(records) == 1
    assert records[0]["proposal_id"] == "audited-1"
    assert records[0]["approved"] is True
    assert "ts" in records[0]


def test_blocked_decision_records_reason_in_audit_log(base_config, kill_switch, circuit_breaker, tmp_path):
    gate = make_gate(base_config, kill_switch, circuit_breaker, tmp_path)
    over_limit_portfolio = PortfolioState(equity=100_000, peak_equity=100_000, cash=100_000)
    gate.evaluate(make_proposal(proposal_id="too-big", quantity=1000, estimated_price=500.0), over_limit_portfolio)
    records = gate.audit_log.read_all()
    assert records[0]["approved"] is False
    assert len(records[0]["blocked_reasons"]) > 0
