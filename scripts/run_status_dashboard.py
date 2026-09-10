#!/usr/bin/env python3
"""Starts the read-only status dashboard (positions, daily P&L, risk limit
headroom, halt state, recent alerts).

This is deliberately a different process and a different port from the
approval dashboard: the page you watch the account on should not be the
page that can authorise an order. This one exposes only GET routes and
has no import path to execution_layer.

Usage:
    python scripts/run_status_dashboard.py

Without a live TWS/Gateway connection it falls back to a placeholder
portfolio derived from config/account.yaml, and says so on the page. Do
not read any percentage off that fallback as if it were real.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401 -- puts the repo root on sys.path

import uvicorn

from config.loader import load_config
from monitoring.factory import build_alert_router
from monitoring.status_dashboard import build_status_app
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.kill_switch import KillSwitch
from risk_gate.models import PortfolioState


def _placeholder_portfolio(config) -> PortfolioState:
    capital = config.account.starting_capital_usd
    return PortfolioState(equity=capital, peak_equity=capital, cash=capital)


def main() -> None:
    config = load_config()
    alert_router = build_alert_router(config)

    def portfolio_provider() -> PortfolioState:
        # Replace with a reconciled IBKR account snapshot before paper
        # trading. Reading live positions is a read-only broker call, but
        # it is still deliberately not wired here by default so that
        # starting this dashboard never opens a broker connection.
        return _placeholder_portfolio(config)

    app = build_status_app(
        config=config,
        portfolio_provider=portfolio_provider,
        kill_switch=KillSwitch(),
        circuit_breaker=CircuitBreaker(),
        alert_router=alert_router,
    )

    host = config.monitoring.status_dashboard_host
    port = config.monitoring.status_dashboard_port
    print(f"status dashboard on http://{host}:{port} (read-only)")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
