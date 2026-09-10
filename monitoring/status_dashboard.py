"""Read-only status dashboard (build spec section 8): current positions,
daily P&L, and risk limit headroom, plus circuit-breaker / kill-switch
state and recent alerts.

Strictly read-only by construction: it exposes only GET routes and holds
no reference to execution_layer or to the proposal store's decision
methods. Approving trades happens on the separate approval dashboard --
keeping the "watch the account" page and the "authorise an order" page
apart means a stray click here can never place a trade.

The portfolio snapshot is supplied by a caller-provided callable rather
than fetched here, so the same page renders from a live reconciled IBKR
snapshot, from a backtest ledger, or from a fixture in tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from monitoring.alerts import AlertRouter
from monitoring.risk_usage import compute_risk_usage

if TYPE_CHECKING:  # pragma: no cover -- import-cycle avoidance
    from config.schema import AppConfig
    from risk_gate.circuit_breaker import CircuitBreaker
    from risk_gate.kill_switch import KillSwitch
    from risk_gate.models import PortfolioState

TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_status_app(
    config: "AppConfig",
    portfolio_provider: Callable[[], "PortfolioState"],
    kill_switch: "KillSwitch | None" = None,
    circuit_breaker: "CircuitBreaker | None" = None,
    alert_router: AlertRouter | None = None,
) -> FastAPI:
    app = FastAPI(title="TradeBot Status Dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def snapshot() -> dict:
        portfolio = portfolio_provider()
        usage = compute_risk_usage(portfolio, config)
        positions = sorted(
            portfolio.positions.values(), key=lambda p: -abs(p.market_value)
        )
        return {
            "as_of": datetime.now(timezone.utc),
            "portfolio": portfolio,
            "positions": positions,
            "risk_usage": usage,
            "breached": [item for item in usage if item.breached],
            "kill_switch_engaged": kill_switch.is_engaged() if kill_switch else False,
            "kill_switch_reason": kill_switch.reason() if kill_switch else None,
            "circuit_breaker": circuit_breaker.info() if circuit_breaker else None,
            "alerts": alert_router.recent(limit=15) if alert_router else [],
            "account_is_placeholder": config.account.is_placeholder,
        }

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(request, "status.html", snapshot())

    @app.get("/api/status")
    def api_status():
        """JSON view of the same data, for scripting or an external
        monitor. Read-only, like everything else on this app."""
        data = snapshot()
        portfolio = data["portfolio"]
        return {
            "as_of": data["as_of"].isoformat(),
            "equity": portfolio.equity,
            "peak_equity": portfolio.peak_equity,
            "cash": portfolio.cash,
            "realized_pnl_today": portfolio.realized_pnl_today,
            "unrealized_pnl_today": portfolio.unrealized_pnl_today,
            "daily_pnl": portfolio.daily_pnl,
            "drawdown_pct": portfolio.drawdown_pct,
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "market_value": p.market_value,
                    "sector": p.sector,
                }
                for p in data["positions"]
            ],
            "risk_usage": [
                {
                    "name": item.name,
                    "used": item.used,
                    "limit": item.limit,
                    "unit": item.unit,
                    "utilization": item.utilization,
                    "headroom": item.headroom,
                    "breached": item.breached,
                }
                for item in data["risk_usage"]
            ],
            "kill_switch_engaged": data["kill_switch_engaged"],
            "circuit_breaker": data["circuit_breaker"],
            "account_is_placeholder": data["account_is_placeholder"],
        }

    return app
