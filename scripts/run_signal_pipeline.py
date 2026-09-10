#!/usr/bin/env python3
"""End-to-end signal pipeline: data_layer -> signal_layer -> risk_gate ->
approval_layer. This stops at a human-reviewable proposal sitting in the
approval dashboard's queue -- nothing here has any path to
execution_layer. Run scripts/run_approval_dashboard.py separately to
review and approve/reject what this produces.

This is a dry-run scaffold: it uses whatever recorded CSV bars exist under
data/recorded_bars/ and a placeholder starting-capital portfolio snapshot.
Before paper trading, replace both with real IBKR market data
(data_layer.market_data.IBKRMarketDataProvider) and a real reconciled
account snapshot (execution_layer.reconciliation) -- using a stale or
placeholder equity figure here would make every risk_gate percentage
check meaningless.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401 -- puts the repo root on sys.path

from approval_layer.store import ProposalStore
from config.loader import load_config
from data_layer.market_data import CSVMarketDataProvider
from monitoring.factory import build_alert_router
from monitoring.signal_log import SignalLog
from risk_gate.gate import RiskGate
from risk_gate.models import PortfolioState
from signal_layer import breakout, mean_reversion, momentum
from signal_layer.sizing import size_signal

STRATEGIES = {
    "momentum": momentum,
    "mean_reversion": mean_reversion,
    "breakout": breakout,
}


def main() -> None:
    config = load_config()
    provider = CSVMarketDataProvider("data/recorded_bars")
    store = ProposalStore("state/approvals.db")
    alert_router = build_alert_router(config)
    signal_log = SignalLog()
    risk_gate = RiskGate(config, alert_router=alert_router)

    portfolio_state = PortfolioState(
        equity=config.account.starting_capital_usd,
        peak_equity=config.account.starting_capital_usd,
        cash=config.account.starting_capital_usd,
    )
    if config.account.is_placeholder:
        print(
            "WARNING: config/account.yaml starting_capital_usd is still a placeholder. "
            "Confirm the real account size before treating any proposal below as real."
        )

    universe = config.universe.include_symbols_only or []
    if not universe:
        print("config/universe.yaml has no include_symbols_only set -- nothing to screen. Exiting.")
        return

    data = {}
    for symbol in universe:
        try:
            data[symbol] = provider.get_historical_bars(symbol)
        except FileNotFoundError as exc:
            print(f"skipping {symbol}: {exc}")

    for strategy_name, module in STRATEGIES.items():
        strategy_config = getattr(config.strategies, strategy_name)
        if not strategy_config.enabled:
            continue

        signals = module.generate_signals(data, strategy_config.params)
        for signal in signals:
            proposal = size_signal(
                signal,
                equity=portfolio_state.equity,
                max_position_pct_of_equity=config.risk_limits.max_position_pct_of_equity,
            )
            if proposal is None:
                # Recorded even though it never became a proposal --
                # otherwise signals that size to zero shares are invisible
                # when judging proposal quality later.
                signal_log.record(signal, outcome="sized_out", note="sizing produced no tradable quantity")
                continue

            decision = risk_gate.evaluate(proposal, portfolio_state)
            if decision.approved:
                signal_log.record(signal, outcome="proposed")
                store.create(proposal, expiry_minutes=config.approval.proposal_expiry_minutes)
                print(f"proposal queued for approval: {proposal.symbol} {proposal.side.value} {proposal.quantity}")
            else:
                signal_log.record(signal, outcome="blocked", note=decision.summary)
                print(f"blocked by risk_gate: {proposal.symbol}: {decision.summary}")


if __name__ == "__main__":
    main()
