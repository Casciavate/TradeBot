# Library & API Decisions (verified August 2026)

Per the build rules, every third-party library and IBKR API surface used in this
repo was checked against current sources before being adopted, rather than
assumed from training data. Findings below; re-verify before any major version
bump or before going live, since this ecosystem moves.

## IBKR Python client: `ib_async`, not `ib_insync`

- `ib_insync` (erdewit/ib_insync) is unmaintained -- the original author is no
  longer maintaining it and the project has no active releases.
- `ib_async` (PyPI: `ib_async` / `ib-async`, GitHub: `ib-api-reloaded/ib_async`)
  is the community-maintained successor and is what this repo depends on.
  Verified installable and importable in this environment at version 2.1.0.
- The official `ibapi` package IBKR ships is *not* reliably published to PyPI
  (PyPI's `ibapi` is stale, last released 2020). IBKR's authoritative
  distribution is the TWS API installer bundled from their API download page.
  This repo does not depend on raw `ibapi` directly -- `ib_async` wraps it.

## TWS / Gateway connection ports

Confirmed default ports (paper vs. live differ, and TWS vs. Gateway differ):

| Platform          | Live | Paper |
|-------------------|------|-------|
| TWS               | 7496 | 7497  |
| IB Gateway        | 4001 | 4002  |

`config/connection.yaml` defaults to the **paper** ports. Nothing in
`signal_layer`, `risk_gate`, or `approval_layer` can change which port is used
-- that is controlled only by `execution_layer`'s connection config plus the
`LIVE_TRADING` environment variable (see `execution_layer/connection.py`, the
only file in the repo that reads it).

## Classic TWS socket API vs. Client Portal Web API

IBKR has not deprecated the classic TWS API in favor of the newer Client
Portal ("IBKR API") web/REST API. The Client Portal API is positioned for
lightweight/custom-UI integrations; the TWS socket API remains the documented
path for programmatic/algorithmic strategies with many simultaneous data
lines. This repo uses the TWS socket API via `ib_async`.

## Historical data limits

`reqHistoricalData`-style calls are still subject to IBKR's long-standing
pacing rules: no more than ~60 requests per rolling 10-minute window (BID_ASK
counts double), no 6+ identical-contract requests within 2 seconds, and
sub-30-second bars are capped to short lookback windows (e.g. 1-second bars
limited to ~30 minutes of history per request). `data_layer` treats these as
hard client-side rate limits, not suggestions -- see `data_layer/market_data.py`.

## Backtesting engine: custom walk-forward event simulator, not `vectorbt`'s `from_signals`

Options considered: `backtrader` (stalled upstream, last PyPI release 2023),
`zipline-reloaded` (alive but slow-moving), `vectorbt` (actively maintained,
fast, numpy/numba-based), `nautilus_trader` (most actively developed and most
"production-parity", but a heavy Rust-core dependency with a much steeper
integration cost for this build).

`vectorbt` is installed and available (verified importable at 1.1.0), but
this repo's `backtest_engine` does not build its core simulation loop on top
of `vectorbt.Portfolio.from_signals`. The reason is architectural, not a
maintenance concern: our momentum strategy is cross-sectional (it ranks the
whole universe and rebalances a shared portfolio) and all three strategies
have stateful, strategy-specific exit rules (time stops, ATR trailing stops,
z-score reversion, breakout failure) evaluated against data that must be
truncated day-by-day to avoid lookahead bias. That combination doesn't map
cleanly onto `from_signals`'s per-symbol boolean entry/exit arrays without
either faking the walk-forward truncation or fighting the API's assumptions
about position sizing across a shared cash pool.

Instead, `backtest_engine/engine.py` is a small, explicit day-by-day
simulator: each day it re-runs `signal_layer` strategies against
data truncated to that day, routes every resulting proposal through the real
`risk_gate.RiskGate` (the same one used live) before opening a position, and
applies `backtest_engine/costs.py`'s commission/slippage/spread model to every
fill. This is slower than a vectorized backtest but is easy to verify
correct, avoids lookahead bias by construction, and means the backtest
actually exercises the same risk limits that would gate a live proposal.
`vectorbt` remains available in `requirements.txt` for ad hoc, single-symbol
vectorized prototyping outside this pipeline if that's ever useful. If the
system later needs full event-driven, order-book-level execution parity,
revisit `nautilus_trader` -- but that is out of scope for the initial build.

## Regulatory note: PDT rule change (flag for account config, not code)

FINRA Regulatory Notice 26-10 (SEC-approved April 2026, effective June 4,
2026, ~18-month phase-in through October 2027) eliminates the classic
"Pattern Day Trader" designation and the $25,000 minimum equity threshold,
replacing it with real-time intraday margin monitoring. This repo does not
hardcode a $25k PDT threshold anywhere. Confirm with IBKR directly how/when
your account's day-trade and margin monitoring behavior changes under the new
rule before relying on any assumption about day-trade limits.
