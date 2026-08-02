#!/usr/bin/env python3
"""Runs a backtest for one strategy against recorded CSV bars and writes a
human-reviewable markdown report. Per the build spec, no strategy proceeds
to paper trading without this report being reviewed by a person.

Usage:
    python scripts/run_backtest.py momentum SPY QQQ IWM --benchmark SPY
"""
from __future__ import annotations

import argparse
from pathlib import Path

from backtest_engine.costs import CostModel
from backtest_engine.engine import run_backtest
from backtest_engine.report import render_markdown
from config.loader import load_config
from data_layer.market_data import CSVMarketDataProvider
from signal_layer import breakout, mean_reversion, momentum

STRATEGIES = {"momentum": momentum, "mean_reversion": mean_reversion, "breakout": breakout}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("strategy", choices=STRATEGIES.keys())
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--data-dir", default="data/recorded_bars")
    parser.add_argument("--out", default="backtest_report.md")
    args = parser.parse_args()

    config = load_config()
    provider = CSVMarketDataProvider(args.data_dir)

    price_data = {symbol: provider.get_historical_bars(symbol) for symbol in args.symbols}
    strategy_config = getattr(config.strategies, args.strategy)

    result = run_backtest(
        price_data=price_data,
        strategy_name=args.strategy,
        strategy_module=STRATEGIES[args.strategy],
        params=strategy_config.params,
        config=config,
        initial_capital=config.account.starting_capital_usd,
        cost_model=CostModel(),
    )

    benchmark_close = None
    if args.benchmark in price_data:
        benchmark_close = price_data[args.benchmark]["close"]
    else:
        try:
            benchmark_close = provider.get_historical_bars(args.benchmark)["close"]
        except FileNotFoundError:
            print(f"no recorded data for benchmark {args.benchmark}; skipping benchmark comparison")

    report = render_markdown(args.strategy, strategy_config.params, result, benchmark_close, args.benchmark)
    Path(args.out).write_text(report)
    print(report)
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()
