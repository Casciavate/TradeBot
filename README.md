# TradeBot

A systematic, risk-gated trade *proposal* engine for Interactive Brokers.
It screens a liquid ETF universe, generates signals from three
transparent, backtestable strategies, sizes and risk-checks candidate
trades, and stops -- every proposal sits in a local approval dashboard
until a human approves or rejects it. Nothing in this repo can send an
order to IBKR unattended.

Read `docs/RISK_ARCHITECTURE.md` before changing anything in `risk_gate/`
or `execution_layer/`. Read `docs/LIBRARY_DECISIONS.md` for why specific
libraries (`ib_async`, not `ib_insync`; a custom backtest loop, not
`vectorbt.Portfolio.from_signals`) were chosen, and re-verify before
bumping a major version -- this ecosystem moves.

## Layout

```
config/            tunable parameters: risk limits, account, universe, strategies, connection
risk_gate/          hard limits every proposal must clear -- independent of strategy code
data_layer/          universe filtering, historical/live market data
signal_layer/        momentum / mean-reversion / breakout strategies (pure functions)
backtest_engine/      walk-forward simulator with commissions/slippage/spread and metrics
approval_layer/       proposal store + local web dashboard for human approve/reject
execution_layer/       IBKR order placement -- only reachable after a recorded approval
monitoring/            shared audit-log primitive
scripts/               CLI entry points (see below)
tests/                 mirrors the package layout above
```

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## Running it

1. `python scripts/run_backtest.py` (see `backtest_engine/`) to validate a
   strategy against history before anything else.
2. `python scripts/run_signal_pipeline.py` to screen the universe and push
   any risk_gate-approved proposals into the approval queue. This is a
   dry-run scaffold: it reads recorded CSV bars from `data/recorded_bars/`
   and uses a placeholder account snapshot -- wire in
   `data_layer.market_data.IBKRMarketDataProvider` and a real reconciled
   account snapshot before paper trading.
3. `python scripts/run_approval_dashboard.py`, open `http://127.0.0.1:8000`,
   and approve or reject what's pending. This is also what actually
   submits an approved order to IBKR (paper by default).
4. `python scripts/kill_switch_cli.py status|engage|disengage` and
   `python scripts/circuit_breaker_cli.py status|reset` for manual control
   independent of everything else running.

## Account context

`config/account.yaml` currently has a **placeholder** starting capital
(`is_placeholder: true`). Confirm the real account size, margin/cash
status, and instrument permissions before treating any risk_gate
percentage-based limit as meaningful. See `docs/RISK_ARCHITECTURE.md`.

## What this is not

A guaranteed-returns system. Risk-adjusted outperformance is a hypothesis
this system is built to test via backtesting and paper trading -- not an
assumed outcome. Every strategy here can be turned off independently in
`config/strategies.yaml`.
