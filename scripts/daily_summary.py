#!/usr/bin/env python3
"""Prints the daily summary: P&L, positions, risk limit usage, and any
circuit breaker trips (build spec section 8).

Built entirely from the append-only audit logs plus one portfolio
snapshot, so it can be regenerated for any past day.

Usage:
    python scripts/daily_summary.py                 # today, UTC
    python scripts/daily_summary.py 2026-09-09      # a specific day
    python scripts/daily_summary.py --email         # also send it as an alert

Without a live connection the portfolio snapshot falls back to
config/account.yaml's starting capital, and the report says so. The
event counts and circuit-breaker section are read from the logs and are
accurate regardless.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401 -- puts the repo root on sys.path

import sys
from datetime import date, datetime, timezone

from config.loader import load_config
from monitoring.alerts import AlertKind, AlertSeverity
from monitoring.daily_summary import build_daily_summary
from monitoring.factory import build_alert_router
from monitoring.risk_usage import breached_limits
from risk_gate.models import PortfolioState

STATE_DIR = "state"
LOG_PATHS = [
    f"{STATE_DIR}/risk_gate_audit.log",
    f"{STATE_DIR}/approval_audit.log",
    f"{STATE_DIR}/execution_audit.log",
    f"{STATE_DIR}/signal_audit.log",
    f"{STATE_DIR}/alerts.log",
    f"{STATE_DIR}/config_audit.log",
]


def _placeholder_portfolio(config) -> PortfolioState:
    capital = config.account.starting_capital_usd
    return PortfolioState(equity=capital, peak_equity=capital, cash=capital)


def main(argv: list[str]) -> int:
    send_email = "--email" in argv
    positional = [arg for arg in argv if not arg.startswith("--")]

    if positional:
        try:
            summary_date = date.fromisoformat(positional[0])
        except ValueError:
            print(f"not a date: {positional[0]} (expected YYYY-MM-DD)")
            return 1
    else:
        summary_date = datetime.now(timezone.utc).date()

    config = load_config()
    portfolio = _placeholder_portfolio(config)

    summary = build_daily_summary(portfolio, config, LOG_PATHS, summary_date)
    text = summary.render_text()
    print(text)

    if send_email:
        router = build_alert_router(config)
        breached = breached_limits(summary.risk_usage)
        severity = AlertSeverity.WARNING if (breached or summary.circuit_breaker_trips) else AlertSeverity.INFO
        router.alert(
            AlertKind.DAILY_SUMMARY,
            severity,
            f"TradeBot daily summary {summary_date.isoformat()}: "
            f"net ${summary.daily_pnl:,.2f} ({summary.daily_pnl_pct:.2%})",
            {"report": text},
            dedup_key=summary_date.isoformat(),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
