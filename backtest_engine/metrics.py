"""Backtest performance metrics, including the required buy-and-hold
benchmark comparison. Every function here takes a plain equity curve /
trade list -- no dependency on the engine itself, so metrics can be unit
tested against hand-built series."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_engine.portfolio import Trade

TRADING_DAYS_PER_YEAR = 252


def cagr(equity_curve: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    if len(equity_curve) < 2 or equity_curve.iloc[0] <= 0:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    years = len(equity_curve) / periods_per_year
    if years <= 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def max_drawdown(equity_curve: pd.Series) -> float:
    if len(equity_curve) == 0:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min())


def sharpe_ratio(equity_curve: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR, risk_free_rate: float = 0.0) -> float:
    returns = equity_curve.pct_change().dropna()
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    return float(np.sqrt(periods_per_year) * excess.mean() / returns.std())


def sortino_ratio(equity_curve: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR, risk_free_rate: float = 0.0) -> float:
    returns = equity_curve.pct_change().dropna()
    if len(returns) == 0:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    return float(np.sqrt(periods_per_year) * excess.mean() / downside.std())


def win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def average_win_loss_ratio(trades: list[Trade]) -> float:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [-t.pnl for t in trades if t.pnl < 0]
    if not wins or not losses:
        return float("nan")
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def benchmark_comparison(equity_curve: pd.Series, benchmark_close: pd.Series) -> dict:
    """Compares the strategy's equity curve against a simple buy-and-hold
    of `benchmark_close` (e.g. SPY) over the same period, rebased to the
    same starting capital."""
    aligned = benchmark_close.reindex(equity_curve.index).ffill().bfill()
    benchmark_curve = aligned / aligned.iloc[0] * equity_curve.iloc[0]

    return {
        "strategy_cagr": cagr(equity_curve),
        "benchmark_cagr": cagr(benchmark_curve),
        "strategy_total_return": float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1),
        "benchmark_total_return": float(benchmark_curve.iloc[-1] / benchmark_curve.iloc[0] - 1),
        "strategy_max_drawdown": max_drawdown(equity_curve),
        "benchmark_max_drawdown": max_drawdown(benchmark_curve),
        "strategy_sharpe": sharpe_ratio(equity_curve),
        "benchmark_sharpe": sharpe_ratio(benchmark_curve),
    }


def summarize(equity_curve: pd.Series, trades: list[Trade], benchmark_close: pd.Series | None = None) -> dict:
    result = {
        "cagr": cagr(equity_curve),
        "max_drawdown": max_drawdown(equity_curve),
        "sharpe": sharpe_ratio(equity_curve),
        "sortino": sortino_ratio(equity_curve),
        "win_rate": win_rate(trades),
        "num_trades": len(trades),
        "avg_win_loss_ratio": average_win_loss_ratio(trades),
        "final_equity": float(equity_curve.iloc[-1]) if len(equity_curve) else 0.0,
    }
    if benchmark_close is not None:
        result["vs_benchmark"] = benchmark_comparison(equity_curve, benchmark_close)
    return result
