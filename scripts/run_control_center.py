#!/usr/bin/env python3
"""Starts the local control center: overview, proposals, activity, controls.

This is the assembly point. It is the script -- not the UI package --
that connects to IBKR and supplies the `on_approved` callback, which is
the only path from an approved proposal to a real order. `control_center`
itself has no import of `execution_layer`, so the boundary holds
structurally.

Usage:
    python scripts/run_control_center.py

Binds to 127.0.0.1 by default. To reach it from another machine, set a
token first and change host in config/ui.yaml:

    export TRADEBOT_UI_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"

Starting on a non-loopback address without that token is refused. Read
docs/UI.md before doing it at all -- a token over plain HTTP is weak auth.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401 -- puts the repo root on sys.path

import uvicorn

from approval_layer.store import ProposalStore
from config.loader import load_config
from control_center.app import build_control_center
from control_center.auth import InsecureBindError, is_loopback, resolve_access_policy
from data_layer.market_data import IBKRMarketDataProvider
from execution_layer.connection import connect
from execution_layer.health import ConnectionWatchdog
from execution_layer.order_manager import OrderManager
from execution_layer.reconciliation import reconcile_positions
from monitoring.factory import build_alert_router
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.kill_switch import KillSwitch
from risk_gate.models import PortfolioState


def _connect_execution_layer(config):
    """Best-effort connect. With nothing running the UI still starts --
    proposals can be reviewed and rejected, and approving one reports that
    it was not submitted rather than silently doing nothing."""
    try:
        ib, target = connect(config.connection)
        mode = "LIVE" if target.is_live else "paper"
        print(f"connected to IBKR on port {target.port} ({mode} trading)")
        return ib, mode
    except Exception as exc:  # noqa: BLE001 -- any connection failure degrades gracefully
        print(f"could not connect to TWS/Gateway ({exc}); approvals will not be submitted.")
        return None, None


def _ibkr_positions(ib) -> dict[str, float]:
    totals: dict[str, float] = {}
    for position in ib.positions():
        symbol = getattr(position.contract, "symbol", None)
        if symbol is None:
            continue
        totals[symbol] = totals.get(symbol, 0.0) + float(position.position)
    return totals


def main() -> int:
    config = load_config()

    try:
        access_policy = resolve_access_policy(config.ui.host, config.ui.token_env_var)
    except InsecureBindError as exc:
        print(f"REFUSING TO START: {exc}")
        return 1

    alert_router = build_alert_router(config)
    store = ProposalStore("state/approvals.db")
    kill_switch = KillSwitch(alert_router=alert_router)
    circuit_breaker = CircuitBreaker(alert_router=alert_router)

    ib, mode = _connect_execution_layer(config)
    order_manager = (
        OrderManager(ib, max_slippage_bps=15.0, alert_router=alert_router) if ib is not None else None
    )
    market_data = IBKRMarketDataProvider(ib) if ib is not None else None
    watchdog = ConnectionWatchdog(ib, alert_router=alert_router) if ib is not None else None

    def execution_status() -> str:
        if watchdog is None:
            return "not connected"
        return f"{mode} connected" if watchdog.check().connected else f"{mode} DISCONNECTED"

    def portfolio_provider() -> PortfolioState:
        # PLACEHOLDER. Replace with a reconciled IBKR account snapshot
        # before paper trading -- until then every percentage the UI shows
        # is measured against config/account.yaml's made-up equity figure,
        # which the page says plainly.
        capital = config.account.starting_capital_usd
        return PortfolioState(equity=capital, peak_equity=capital, cash=capital)

    def on_approved(proposal):
        # The only path into execution_layer in this codebase, reached
        # only after ProposalStore.approve() recorded a human decision.
        if order_manager is None:
            raise RuntimeError("no IBKR connection -- start TWS/Gateway and restart the UI")
        if watchdog is not None and not watchdog.check().connected:
            raise RuntimeError("IBKR connection is down -- refusing to submit into an unverified session")

        reference_price = market_data.get_latest_price(proposal.symbol)
        record = order_manager.submit_order(proposal, reference_price=reference_price)
        print(f"[submitted] {proposal.symbol} {proposal.side} {proposal.quantity} -> "
              f"order {record.ibkr_order_id} ({record.state.value})")
        reconcile_positions(
            order_manager.local_positions(), _ibkr_positions(ib), alert_router=alert_router
        )

    app = build_control_center(
        config=config,
        store=store,
        portfolio_provider=portfolio_provider,
        kill_switch=kill_switch,
        circuit_breaker=circuit_breaker,
        alert_router=alert_router,
        on_approved=on_approved,
        access_policy=access_policy,
        default_operator_name=config.ui.operator_name,
        execution_status=execution_status,
    )

    host, port = config.ui.host, config.ui.port
    print(f"control center on http://{host}:{port}")
    if not is_loopback(host):
        print("WARNING: bound beyond loopback. This UI can authorise real orders -- make sure "
              "there is TLS and real authentication in front of it.")
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
