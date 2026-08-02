from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backtest_engine.metrics import (
    average_win_loss_ratio,
    benchmark_comparison,
    cagr,
    max_drawdown,
    sharpe_ratio,
    win_rate,
)
from backtest_engine.portfolio import Trade
from risk_gate.models import Side


def make_equity_curve(values: list[float]) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=dates)


def make_trade(pnl: float) -> Trade:
    return Trade(
        symbol="SPY",
        strategy_name="momentum",
        side=Side.BUY,
        quantity=10,
        entry_date=date(2024, 1, 1),
        entry_price=100.0,
        exit_date=date(2024, 1, 5),
        exit_price=100.0 + pnl / 10,
        pnl=pnl,
        exit_reason="target",
    )


def test_cagr_of_flat_curve_is_zero():
    curve = make_equity_curve([100_000] * 252)
    assert cagr(curve) == pytest.approx(0.0, abs=1e-9)


def test_cagr_doubling_over_one_year():
    curve = make_equity_curve([100_000, 200_000] + [200_000] * 250)
    result = cagr(curve, periods_per_year=252)
    assert result > 0


def test_max_drawdown_detects_peak_to_trough():
    curve = make_equity_curve([100_000, 120_000, 90_000, 110_000])
    dd = max_drawdown(curve)
    assert dd == pytest.approx((90_000 - 120_000) / 120_000)


def test_sharpe_ratio_zero_for_zero_variance():
    curve = make_equity_curve([100_000] * 10)
    assert sharpe_ratio(curve) == 0.0


def test_win_rate_computes_fraction_of_winning_trades():
    trades = [make_trade(100), make_trade(-50), make_trade(200), make_trade(-10)]
    assert win_rate(trades) == 0.5


def test_win_rate_empty_trades_is_zero():
    assert win_rate([]) == 0.0


def test_average_win_loss_ratio():
    trades = [make_trade(100), make_trade(-50)]
    assert average_win_loss_ratio(trades) == pytest.approx(2.0)


def test_benchmark_comparison_flags_underperformance():
    strategy_curve = make_equity_curve([100_000] * 252)  # flat
    benchmark = make_equity_curve([100.0 * (1.001**i) for i in range(252)])  # steadily up
    comparison = benchmark_comparison(strategy_curve, benchmark)
    assert comparison["benchmark_cagr"] > comparison["strategy_cagr"]
    assert comparison["strategy_total_return"] == pytest.approx(0.0, abs=1e-9)
