from __future__ import annotations

from risk_gate.limits import (
    check_daily_loss_circuit_breaker,
    check_drawdown_circuit_breaker,
    check_leverage,
    check_max_order_notional,
    check_max_position_size,
    check_no_naked_short,
    check_sector_concentration,
)
from risk_gate.models import PortfolioState, Position, Side
from tests.risk_gate.conftest import make_proposal


def test_max_order_notional_passes_under_ceiling(base_config, flat_portfolio):
    proposal = make_proposal(quantity=10, estimated_price=500.0)  # $5,000
    result = check_max_order_notional(proposal, flat_portfolio, base_config)
    assert result.passed


def test_max_order_notional_blocks_over_ceiling(base_config, flat_portfolio):
    proposal = make_proposal(quantity=100, estimated_price=500.0)  # $50,000 > $15,000 ceiling
    result = check_max_order_notional(proposal, flat_portfolio, base_config)
    assert not result.passed
    assert "ceiling" in result.reason


def test_max_position_size_blocks_when_resulting_position_too_large(base_config, flat_portfolio):
    # 8% of $100k = $8,000 cap; this order alone is $9,000
    proposal = make_proposal(quantity=18, estimated_price=500.0)
    result = check_max_position_size(proposal, flat_portfolio, base_config)
    assert not result.passed


def test_max_position_size_accounts_for_existing_position(base_config):
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=90_000,
        positions={"SPY": Position(symbol="SPY", quantity=14, market_value=7_000, sector="Broad Market")},
    )
    # Existing $7,000 + new $2,000 = $9,000 > 8% of equity ($8,000)
    proposal = make_proposal(quantity=4, estimated_price=500.0)
    result = check_max_position_size(proposal, portfolio, base_config)
    assert not result.passed


def test_max_position_size_sell_reduces_exposure(base_config):
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=90_000,
        positions={"SPY": Position(symbol="SPY", quantity=20, market_value=10_000, sector="Broad Market")},
    )
    # Existing exposure already breaches the cap, but a SELL should reduce it, not block it.
    proposal = make_proposal(side=Side.SELL, quantity=10, estimated_price=500.0)
    result = check_max_position_size(proposal, portfolio, base_config)
    assert result.passed


def test_sector_concentration_blocks_over_limit(base_config):
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=60_000,
        positions={
            "XLF": Position(symbol="XLF", quantity=100, market_value=20_000, sector="Financials"),
        },
    )
    # 20,000 existing + 6,000 new = 26,000 > 25% of 100k = 25,000
    proposal = make_proposal(symbol="KBE", quantity=12, estimated_price=500.0, sector="Financials")
    result = check_sector_concentration(proposal, portfolio, base_config)
    assert not result.passed


def test_leverage_blocks_when_gross_exposure_exceeds_cap(base_config):
    portfolio = PortfolioState(equity=100_000, peak_equity=100_000, cash=5_000, positions={
        "SPY": Position(symbol="SPY", quantity=190, market_value=95_000, sector="Broad Market"),
    })
    proposal = make_proposal(symbol="QQQ", quantity=20, estimated_price=500.0, sector="Tech")
    result = check_leverage(proposal, portfolio, base_config)
    assert not result.passed


def test_no_naked_short_blocks_sell_beyond_position_on_cash_account(base_config, flat_portfolio):
    proposal = make_proposal(side=Side.SELL, quantity=10, estimated_price=500.0)
    result = check_no_naked_short(proposal, flat_portfolio, base_config)
    assert not result.passed


def test_no_naked_short_allows_selling_down_to_flat(base_config):
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=95_000,
        positions={"SPY": Position(symbol="SPY", quantity=10, market_value=5_000, sector="Broad Market")},
    )
    proposal = make_proposal(side=Side.SELL, quantity=10, estimated_price=500.0)
    result = check_no_naked_short(proposal, portfolio, base_config)
    assert result.passed


def test_daily_loss_circuit_breaker_trips_at_threshold(base_config):
    portfolio = PortfolioState(
        equity=97_400, peak_equity=100_000, cash=97_400, realized_pnl_today=-2_600
    )
    proposal = make_proposal()
    result = check_daily_loss_circuit_breaker(proposal, portfolio, base_config)
    assert not result.passed


def test_daily_loss_circuit_breaker_passes_under_threshold(base_config):
    portfolio = PortfolioState(
        equity=99_000, peak_equity=100_000, cash=99_000, realized_pnl_today=-1_000
    )
    proposal = make_proposal()
    result = check_daily_loss_circuit_breaker(proposal, portfolio, base_config)
    assert result.passed


def test_drawdown_circuit_breaker_trips_at_threshold(base_config):
    portfolio = PortfolioState(equity=87_000, peak_equity=100_000, cash=87_000)
    proposal = make_proposal()
    result = check_drawdown_circuit_breaker(proposal, portfolio, base_config)
    assert not result.passed


def test_drawdown_circuit_breaker_passes_under_threshold(base_config):
    portfolio = PortfolioState(equity=95_000, peak_equity=100_000, cash=95_000)
    proposal = make_proposal()
    result = check_drawdown_circuit_breaker(proposal, portfolio, base_config)
    assert result.passed
