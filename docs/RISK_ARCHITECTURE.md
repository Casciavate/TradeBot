# Risk architecture

This describes the non-negotiable rules this repo is built around. If a
change would violate one of these, that's a sign to stop and reconsider,
not to work around it.

## Boundaries strategy code cannot cross

1. **Paper by default.** `execution_layer/connection.py` is the only file
   in the repo that reads the `LIVE_TRADING` environment variable
   (`tests/test_live_trading_boundary.py` enforces this structurally on
   every test run). Nothing in `config/`, `signal_layer/`, or `risk_gate/`
   can set it, because none of them touch it at all. Unset or anything
   other than exactly `"true"` means paper port, always.

2. **risk_gate is a mandatory chokepoint.** Every `OrderProposal` --
   whether it comes from live signal generation or from
   `backtest_engine`'s simulation loop -- passes through
   `risk_gate.RiskGate.evaluate()` before it can become an approved
   proposal. The checks themselves (`risk_gate/limits.py`) are pure
   functions with no dependency on `signal_layer`, so strategy code cannot
   influence what counts as a violation.

3. **No order reaches IBKR without a recorded human approval.**
   `execution_layer.order_manager.OrderManager.submit_order` is the only
   function in the codebase that calls a broker client's `placeOrder`.
   The only caller of it is the `on_approved` callback wired in
   `scripts/run_approval_dashboard.py`, which only fires after
   `approval_layer.store.ProposalStore.approve()` has written a decision
   record. `tests/test_live_trading_boundary.py` also asserts
   `signal_layer` and `risk_gate` never import `execution_layer` or
   `ib_async` directly.

4. **Circuit breakers latch until a human clears them.**
   `risk_gate.circuit_breaker.CircuitBreaker` persists to a JSON file on
   disk; once tripped by a daily-loss or drawdown breach, it stays tripped
   across process restarts and even if the next portfolio snapshot looks
   fine. Only `scripts/circuit_breaker_cli.py reset` clears it.

5. **The kill switch is a file.** `risk_gate.kill_switch.KillSwitch`
   checks for the existence of `state/KILL_SWITCH`. It can be engaged by
   `scripts/kill_switch_cli.py`, by any other process, or by a human
   running `touch state/KILL_SWITCH` directly -- it does not depend on any
   Python process being alive to take effect.

6. **Config changes are diffed and logged.** `config/loader.py` snapshots
   `risk_limits.yaml` and `account.yaml` on every load and writes a
   timestamped diff to `state/config_audit.log` whenever either changes.

## Current limits

See `config/risk_limits.yaml` for the live values (position size cap,
sector concentration cap, absolute per-order notional ceiling, daily-loss
and drawdown circuit breakers, order rate limits, leverage cap). Treat
every value there as a hypothesis to tune deliberately, not a default to
leave unexamined -- and remember any change shows up in the audit log.

## Before this system touches real money

Per section 9 of the original build spec:

1. Unit tests for `signal_layer` and `risk_gate` pass with no live
   connection required (`pytest tests/risk_gate tests/signal_layer`).
2. A multi-year backtest (`backtest_engine`), including at least one bear
   market, has been run and its `backtest_engine.report` reviewed by a
   human -- not just "the numbers looked fine."
3. Paper trading for a minimum observation period (weeks, not days),
   comparing live paper performance against backtest expectations. A large
   divergence means stop and investigate, not "wait and see."
4. An explicit kill-switch test in paper mode: engage
   `scripts/kill_switch_cli.py engage "test"`, confirm no new proposal can
   be approved into an order, then disengage.
5. If going live at all: start with a small fraction of intended capital,
   and only scale up after an observation period with zero risk-limit
   breaches.

`config/account.yaml`'s `starting_capital_usd` is currently a placeholder
(`is_placeholder: true`). Do not treat any risk-limit percentage as
meaningful until that is replaced with the real, confirmed account size
and `is_placeholder` is flipped to `false`.
