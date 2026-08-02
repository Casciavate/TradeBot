"""Day-by-day walk-forward backtest simulator. See
docs/LIBRARY_DECISIONS.md for why this is a custom loop rather than
vectorbt's from_signals.

Every proposal generated during the backtest is routed through the same
risk_gate.RiskGate used live, so the backtest reports what the system
would actually have been allowed to do -- not an idealized, unconstrained
version of the strategy. No lookahead: a strategy only ever sees
`price_data` truncated up to and including the current simulated day.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from backtest_engine.costs import CostModel
from backtest_engine.exit_rules import check_exit
from backtest_engine.portfolio import SimPortfolio, Trade
from config.schema import AppConfig
from monitoring.audit_log import AuditLog
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.gate import RiskGate
from risk_gate.kill_switch import KillSwitch
from signal_layer.indicators import rolling_high
from signal_layer.sizing import size_signal


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)
    approved_proposals: int = 0
    blocked_proposals: int = 0
    blocked_reasons_sample: list[str] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1])


def make_isolated_risk_gate(config: AppConfig) -> RiskGate:
    """A RiskGate bound to a fresh temp directory. Backtests must never
    read or write the live kill switch / circuit breaker / audit log --
    that would let a backtest run trip (or worse, silently inherit) real
    trading-halt state."""
    tmp_dir = tempfile.mkdtemp(prefix="tradebot_backtest_")
    return RiskGate(
        config=config,
        kill_switch=KillSwitch(path=f"{tmp_dir}/KILL_SWITCH"),
        circuit_breaker=CircuitBreaker(path=f"{tmp_dir}/circuit_breaker.json"),
        audit_log=AuditLog(f"{tmp_dir}/risk_gate_audit.log"),
    )


def run_backtest(
    price_data: dict[str, pd.DataFrame],
    strategy_name: str,
    strategy_module,
    params: dict,
    config: AppConfig,
    initial_capital: float,
    cost_model: CostModel | None = None,
    min_lookback_days: int = 60,
    risk_gate: RiskGate | None = None,
) -> BacktestResult:
    cost_model = cost_model or CostModel()
    risk_gate = risk_gate or make_isolated_risk_gate(config)

    symbols = list(price_data.keys())
    if not symbols:
        raise ValueError("price_data is empty")

    reference_index = price_data[symbols[0]].index
    for symbol in symbols[1:]:
        if not price_data[symbol].index.equals(reference_index):
            raise ValueError(
                f"{symbol} does not share the same trading calendar as {symbols[0]} -- "
                "align all symbols to a common index before backtesting"
            )

    sectors = {s: df.attrs.get("sector", "Unknown") for s, df in price_data.items()}
    max_position_pct = config.risk_limits.max_position_pct_of_equity
    rebalance_every_days = params.get("rebalance_every_days")

    portfolio = SimPortfolio(initial_capital, cost_model)
    equity_points: list[tuple] = []
    approved_count = 0
    blocked_count = 0
    blocked_reasons_sample: list[str] = []
    days_since_rebalance = 0

    for i, current_date in enumerate(reference_index):
        if i < min_lookback_days:
            equity_points.append((current_date, initial_capital))
            continue

        data_to_date = {}
        for s in symbols:
            truncated = price_data[s].iloc[: i + 1]
            truncated.attrs["sector"] = sectors[s]
            data_to_date[s] = truncated
        marks = {s: float(data_to_date[s]["close"].iloc[-1]) for s in symbols}
        now = datetime.combine(current_date.date(), datetime.min.time(), tzinfo=timezone.utc)

        # --- 1. exits, checked every day for every open position ---
        for symbol in list(portfolio.positions.keys()):
            position = portfolio.positions[symbol]
            should_exit, reason = check_exit(
                position.strategy_name, position, current_date.date(), marks[symbol], data_to_date[symbol], params
            )
            if should_exit:
                portfolio.close_position(symbol, current_date.date(), marks[symbol], reason)

        # --- 2. entries (and momentum rebalance exits) ---
        is_momentum_rebalance_day = False
        if strategy_name == "momentum":
            is_momentum_rebalance_day = rebalance_every_days is None or days_since_rebalance >= rebalance_every_days
            days_since_rebalance = 0 if is_momentum_rebalance_day else days_since_rebalance + 1

        signals = []
        if strategy_name != "momentum" or is_momentum_rebalance_day:
            signals = strategy_module.generate_signals(data_to_date, params)

        if strategy_name == "momentum" and is_momentum_rebalance_day:
            target_symbols = {s.symbol for s in signals}
            for symbol in list(portfolio.positions.keys()):
                if portfolio.positions[symbol].strategy_name == "momentum" and symbol not in target_symbols:
                    portfolio.close_position(symbol, current_date.date(), marks[symbol], "rebalance_exit")

        for signal in signals:
            if signal.symbol in portfolio.positions:
                continue

            portfolio_state = portfolio.to_risk_gate_state(marks, sectors)
            proposal = size_signal(
                signal,
                equity=portfolio_state.equity,
                max_position_pct_of_equity=max_position_pct,
                proposal_id=f"{signal.symbol}-{strategy_name}-{current_date.date()}",
            )
            if proposal is None:
                continue

            decision = risk_gate.evaluate(proposal, portfolio_state, now=now)
            if not decision.approved:
                blocked_count += 1
                if len(blocked_reasons_sample) < 20:
                    blocked_reasons_sample.append(f"{proposal.symbol} {current_date.date()}: {decision.summary}")
                continue

            extra = {"sector": signal.sector}
            if strategy_name == "breakout":
                extra["breakout_level"] = rolling_high(data_to_date[signal.symbol]["close"], params["lookback_days"])

            opened = portfolio.open_position(
                proposal,
                entry_date=current_date.date(),
                stop_loss_price=signal.stop_loss_price,
                target_price=signal.target_price,
                extra=extra,
            )
            if opened:
                approved_count += 1

        marks_after_trades = {s: float(data_to_date[s]["close"].iloc[-1]) for s in symbols}
        portfolio.set_daily_baseline(marks_after_trades)
        equity_points.append((current_date, portfolio.equity(marks_after_trades)))

    equity_curve = pd.Series(
        [v for _, v in equity_points], index=[d for d, _ in equity_points], name="equity"
    )
    return BacktestResult(
        equity_curve=equity_curve,
        trades=portfolio.closed_trades,
        approved_proposals=approved_count,
        blocked_proposals=blocked_count,
        blocked_reasons_sample=blocked_reasons_sample,
    )
