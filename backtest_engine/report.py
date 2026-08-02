"""Formats a human-reviewable backtest report. Per the build spec, no
strategy proceeds to paper trading without this report being reviewed by a
human -- this module only formats it, nothing here auto-approves anything."""
from __future__ import annotations

from backtest_engine.engine import BacktestResult
from backtest_engine.metrics import summarize


def render_markdown(
    strategy_name: str,
    params: dict,
    result: BacktestResult,
    benchmark_close=None,
    benchmark_symbol: str = "SPY",
) -> str:
    metrics = summarize(result.equity_curve, result.trades, benchmark_close)

    lines = [
        f"# Backtest report: {strategy_name}",
        "",
        f"Params: `{params}`",
        "",
        "## Performance",
        "",
        f"- CAGR: {metrics['cagr']:.2%}",
        f"- Max drawdown: {metrics['max_drawdown']:.2%}",
        f"- Sharpe: {metrics['sharpe']:.2f}",
        f"- Sortino: {metrics['sortino']:.2f}",
        f"- Win rate: {metrics['win_rate']:.2%} ({metrics['num_trades']} trades)",
        f"- Avg win/loss ratio: {metrics['avg_win_loss_ratio']:.2f}",
        f"- Final equity: ${metrics['final_equity']:,.2f}",
        "",
    ]

    if "vs_benchmark" in metrics:
        b = metrics["vs_benchmark"]
        lines += [
            f"## Vs. buy-and-hold {benchmark_symbol}",
            "",
            f"- Strategy CAGR: {b['strategy_cagr']:.2%} | {benchmark_symbol} CAGR: {b['benchmark_cagr']:.2%}",
            f"- Strategy total return: {b['strategy_total_return']:.2%} | "
            f"{benchmark_symbol} total return: {b['benchmark_total_return']:.2%}",
            f"- Strategy max drawdown: {b['strategy_max_drawdown']:.2%} | "
            f"{benchmark_symbol} max drawdown: {b['benchmark_max_drawdown']:.2%}",
            f"- Strategy Sharpe: {b['strategy_sharpe']:.2f} | {benchmark_symbol} Sharpe: {b['benchmark_sharpe']:.2f}",
            "",
        ]

    lines += [
        "## risk_gate activity during this backtest",
        "",
        f"- Approved proposals: {result.approved_proposals}",
        f"- Blocked proposals: {result.blocked_proposals}",
    ]
    if result.blocked_reasons_sample:
        lines.append("- Sample of blocked reasons:")
        for reason in result.blocked_reasons_sample:
            lines.append(f"  - {reason}")
    lines.append("")
    lines.append(
        "**This report requires human review before the strategy proceeds to paper "
        "trading.** Outperformance here is a backtested hypothesis, not a live guarantee."
    )

    return "\n".join(lines)
