#!/usr/bin/env python3
"""Starts the local trade-approval dashboard. Bind host defaults to
localhost only -- this dashboard controls whether real orders reach
execution_layer, so it should not be exposed beyond the machine it's
running on without adding real authentication first.

Usage:
    python scripts/run_approval_dashboard.py
"""
from __future__ import annotations

import uvicorn

from approval_layer.dashboard import build_app
from approval_layer.store import ProposalStore
from config.loader import load_config
from data_layer.market_data import IBKRMarketDataProvider
from execution_layer.connection import connect
from execution_layer.order_manager import OrderManager


def _connect_execution_layer(config):
    """Best-effort connect to TWS/Gateway. If nothing is running (common
    during development), the dashboard still starts -- proposals can be
    reviewed and rejected, but approving one will show an error instead of
    silently doing nothing."""
    try:
        ib, target = connect(config.connection)
        mode = "LIVE" if target.is_live else "paper"
        print(f"execution_layer connected to IBKR on port {target.port} ({mode} trading)")
        return ib
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any connection failure degrades gracefully
        print(f"execution_layer could not connect to TWS/Gateway ({exc}); approvals will not be submitted.")
        return None


def main() -> None:
    config = load_config()
    store = ProposalStore("state/approvals.db")

    ib = _connect_execution_layer(config)
    order_manager = OrderManager(ib, max_slippage_bps=15.0) if ib is not None else None
    market_data = IBKRMarketDataProvider(ib) if ib is not None else None

    def on_approved(proposal):
        # The only path into execution_layer in this whole codebase --
        # reached only after ProposalStore.approve() has recorded a human
        # decision. approval_layer itself never imports execution_layer;
        # this callback is supplied by this assembly script.
        if order_manager is None:
            print(f"[approved but NOT submitted -- no IBKR connection] {proposal.symbol} {proposal.side} {proposal.quantity}")
            return
        reference_price = market_data.get_latest_price(proposal.symbol)
        record = order_manager.submit_order(proposal, reference_price=reference_price)
        print(f"[submitted] {proposal.symbol} {proposal.side} {proposal.quantity} -> order {record.ibkr_order_id} ({record.state.value})")

    app = build_app(
        store=store,
        allow_bulk_approve=config.approval.allow_bulk_approve,
        on_approved=on_approved,
    )
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
