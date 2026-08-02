from __future__ import annotations

import pytest

from config.schema import (
    AccountConfig,
    ApprovalConfig,
    AppConfig,
    ConnectionConfig,
    RiskLimitsConfig,
    StrategiesConfig,
    StrategyConfig,
    UniverseConfig,
)
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.kill_switch import KillSwitch
from risk_gate.models import OrderProposal, PortfolioState, Position, Side


@pytest.fixture
def base_config() -> AppConfig:
    return AppConfig(
        account=AccountConfig(
            starting_capital_usd=100_000,
            is_placeholder=True,
            account_type="margin_no_leverage",
        ),
        risk_limits=RiskLimitsConfig(
            max_position_pct_of_equity=0.08,
            max_sector_concentration_pct=0.25,
            max_single_order_notional_usd=15_000,
            max_daily_loss_pct=0.025,
            max_drawdown_pct=0.12,
            max_orders_per_minute=5,
            max_orders_per_hour=30,
            max_leverage=1.0,
        ),
        universe=UniverseConfig(
            allowed_asset_classes=["ETF"],
            min_avg_dollar_volume_usd=10_000_000,
            min_price_usd=5.0,
        ),
        strategies=StrategiesConfig(
            momentum=StrategyConfig(enabled=True, params={}),
            mean_reversion=StrategyConfig(enabled=True, params={}),
            breakout=StrategyConfig(enabled=True, params={}),
        ),
        approval=ApprovalConfig(proposal_expiry_minutes=30, allow_bulk_approve=False),
        connection=ConnectionConfig(),
    )


@pytest.fixture
def flat_portfolio() -> PortfolioState:
    return PortfolioState(equity=100_000, peak_equity=100_000, cash=100_000)


def make_proposal(
    symbol: str = "SPY",
    side: Side = Side.BUY,
    quantity: float = 10,
    estimated_price: float = 500.0,
    sector: str = "Broad Market",
    strategy_name: str = "momentum",
    proposal_id: str = "test-proposal-1",
) -> OrderProposal:
    return OrderProposal(
        proposal_id=proposal_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        estimated_price=estimated_price,
        sector=sector,
        strategy_name=strategy_name,
        reasoning="test fixture",
    )


@pytest.fixture
def kill_switch(tmp_path) -> KillSwitch:
    return KillSwitch(path=tmp_path / "KILL_SWITCH")


@pytest.fixture
def circuit_breaker(tmp_path) -> CircuitBreaker:
    return CircuitBreaker(path=tmp_path / "circuit_breaker.json")
