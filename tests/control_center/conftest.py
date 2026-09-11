from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from approval_layer.store import ProposalStore
from control_center.app import build_control_center
from monitoring.alerts import AlertRouter
from monitoring.audit_log import AuditLog
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.kill_switch import KillSwitch
from risk_gate.models import OrderProposal, PortfolioState, Position, Side
from tests.risk_gate.conftest import base_config  # noqa: F401 -- re-exported fixture


@pytest.fixture
def portfolio() -> PortfolioState:
    return PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=95_000,
        positions={"SPY": Position("SPY", 10, 5_000, "Broad Market")},
        realized_pnl_today=-250,
        unrealized_pnl_today=100,
    )


@pytest.fixture
def store(tmp_path) -> ProposalStore:
    return ProposalStore(tmp_path / "approvals.db", audit_log=AuditLog(tmp_path / "approval.log"))


@pytest.fixture
def kill_switch(tmp_path) -> KillSwitch:
    return KillSwitch(path=tmp_path / "KILL_SWITCH")


@pytest.fixture
def circuit_breaker(tmp_path) -> CircuitBreaker:
    return CircuitBreaker(path=tmp_path / "circuit_breaker.json")


@pytest.fixture
def alert_router(tmp_path) -> AlertRouter:
    return AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)


def make_proposal(symbol: str = "SPY", proposal_id: str = "p1", side: Side = Side.BUY) -> OrderProposal:
    return OrderProposal(
        proposal_id=proposal_id,
        symbol=symbol,
        side=side,
        quantity=10,
        estimated_price=500.0,
        sector="Broad Market",
        strategy_name="momentum",
        reasoning="momentum rank 2 of 40",
        stop_loss_price=450.0,
    )


@pytest.fixture
def app_factory(base_config, store, portfolio, kill_switch, circuit_breaker, alert_router, tmp_path):
    def factory(**overrides):
        kwargs = dict(
            config=base_config,
            store=store,
            portfolio_provider=lambda: portfolio,
            kill_switch=kill_switch,
            circuit_breaker=circuit_breaker,
            alert_router=alert_router,
            log_paths=(tmp_path / "approval.log", tmp_path / "alerts.log"),
        )
        kwargs.update(overrides)
        return build_control_center(**kwargs)

    return factory


@pytest.fixture
def client(app_factory) -> TestClient:
    return TestClient(app_factory())
