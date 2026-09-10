from __future__ import annotations

import pytest

from monitoring.risk_usage import breached_limits, compute_risk_usage
from risk_gate.models import PortfolioState, Position


def _usage_by_name(usage):
    return {item.name: item for item in usage}


def test_flat_portfolio_uses_no_position_or_sector_headroom(base_config, flat_portfolio):
    usage = _usage_by_name(compute_risk_usage(flat_portfolio, base_config))

    assert usage["largest position"].used == 0.0
    assert usage["largest position"].limit == pytest.approx(8_000)
    assert usage["largest position"].headroom == pytest.approx(8_000)
    assert usage["largest sector exposure"].used == 0.0
    assert usage["gross leverage"].used == 0.0


def test_largest_position_and_sector_are_reported(base_config):
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=50_000,
        positions={
            "SPY": Position("SPY", 10, 6_000, "Broad Market"),
            "QQQ": Position("QQQ", 5, 4_000, "Broad Market"),
            "GLD": Position("GLD", 20, 3_000, "Commodity"),
        },
    )

    usage = _usage_by_name(compute_risk_usage(portfolio, base_config))

    assert usage["largest position"].used == pytest.approx(6_000)
    assert usage["largest position"].detail == "SPY"
    assert usage["largest sector exposure"].used == pytest.approx(10_000)
    assert usage["largest sector exposure"].detail == "Broad Market"


def test_utilization_and_headroom_are_consistent(base_config):
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=96_000,
        positions={"SPY": Position("SPY", 10, 4_000, "Broad Market")},
    )

    usage = _usage_by_name(compute_risk_usage(portfolio, base_config))
    position = usage["largest position"]

    assert position.utilization == pytest.approx(0.5)
    assert position.headroom == pytest.approx(4_000)
    assert not position.breached


def test_daily_loss_and_drawdown_track_the_circuit_breaker_thresholds(base_config):
    portfolio = PortfolioState(
        equity=90_000,
        peak_equity=100_000,
        cash=90_000,
        realized_pnl_today=-3_000,
        unrealized_pnl_today=0,
    )

    usage = _usage_by_name(compute_risk_usage(portfolio, base_config))

    assert usage["daily loss"].used == pytest.approx(3_000 / 90_000)
    assert usage["daily loss"].limit == pytest.approx(0.025)
    assert usage["daily loss"].breached
    assert usage["drawdown from peak"].used == pytest.approx(0.10)
    assert not usage["drawdown from peak"].breached


def test_breached_limits_surfaces_only_limits_at_or_over_the_cap(base_config):
    portfolio = PortfolioState(
        equity=90_000,
        peak_equity=100_000,
        cash=90_000,
        realized_pnl_today=-3_000,
    )

    breached = breached_limits(compute_risk_usage(portfolio, base_config))

    assert [item.name for item in breached] == ["daily loss"]


def test_utilization_is_not_clipped_when_a_limit_is_exceeded(base_config):
    """A breach must read as e.g. 140% so the size of the overrun is
    visible, not silently clipped to 100%."""
    portfolio = PortfolioState(
        equity=100_000,
        peak_equity=100_000,
        cash=0,
        positions={"SPY": Position("SPY", 30, 12_000, "Broad Market")},
    )

    usage = _usage_by_name(compute_risk_usage(portfolio, base_config))

    assert usage["largest position"].utilization == pytest.approx(1.5)
    assert usage["largest position"].breached
    assert usage["largest position"].headroom == 0.0


def test_zero_equity_does_not_divide_by_zero(base_config):
    portfolio = PortfolioState(equity=0, peak_equity=100_000, cash=0)

    usage = _usage_by_name(compute_risk_usage(portfolio, base_config))

    assert usage["gross leverage"].used == 0.0
    assert usage["largest position"].utilization == 0.0


def test_values_format_with_their_declared_unit(base_config, flat_portfolio):
    usage = _usage_by_name(compute_risk_usage(flat_portfolio, base_config))

    assert usage["largest position"].format_limit() == "$8,000.00"
    assert usage["daily loss"].format_limit() == "2.50%"
    assert usage["gross leverage"].format_limit() == "1.00x"
