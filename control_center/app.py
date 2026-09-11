"""The control center web app.

One local UI with four pages: overview (halt state, P&L, positions, risk
headroom), proposals (approve/reject), activity (unified audit-log feed),
and controls (kill switch, circuit breaker).

Two boundaries are preserved deliberately and enforced by tests:

1. **No import of execution_layer.** The callback that turns an approved
   proposal into an IBKR order is injected by the launch script. This
   module can record an approval; it cannot place an order.
2. **Re-enabling trading is never one click.** Engaging the kill switch
   is a single button, because halting is always the safe direction.
   Disengaging it, and resetting a tripped circuit breaker, both require
   typing an explicit confirmation phrase plus an operator name, and both
   are logged. That keeps "a human must deliberately re-enable trading"
   true of the UI as well as the CLI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from approval_layer.models import StoredProposal
from approval_layer.store import (
    BulkApprovalDisabledError,
    ProposalAlreadyDecidedError,
    ProposalExpiredError,
    ProposalStore,
)
from control_center.activity import known_categories, load_activity
from control_center.auth import SESSION_COOKIE, AccessPolicy
from monitoring.alerts import AlertRouter
from monitoring.risk_usage import compute_risk_usage

if TYPE_CHECKING:  # pragma: no cover -- import-cycle avoidance
    from config.schema import AppConfig
    from risk_gate.circuit_breaker import CircuitBreaker
    from risk_gate.kill_switch import KillSwitch
    from risk_gate.models import PortfolioState

TEMPLATES_DIR = Path(__file__).parent / "templates"

DISENGAGE_PHRASE = "RESUME TRADING"

DEFAULT_LOG_PATHS = (
    "state/signal_audit.log",
    "state/risk_gate_audit.log",
    "state/approval_audit.log",
    "state/execution_audit.log",
    "state/alerts.log",
    "state/config_audit.log",
)


def build_control_center(
    config: "AppConfig",
    store: ProposalStore,
    portfolio_provider: Callable[[], "PortfolioState"],
    kill_switch: "KillSwitch",
    circuit_breaker: "CircuitBreaker",
    alert_router: AlertRouter | None = None,
    on_approved: Callable[[StoredProposal], None] | None = None,
    access_policy: AccessPolicy | None = None,
    log_paths: tuple[str, ...] = DEFAULT_LOG_PATHS,
    default_operator_name: str = "",
    execution_status: Callable[[], str] | None = None,
) -> FastAPI:
    app = FastAPI(title="TradeBot Control Center")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    on_approved = on_approved or (lambda proposal: None)
    access_policy = access_policy or AccessPolicy(required=False, token=None)
    execution_status = execution_status or (lambda: "not connected")

    def halt_state() -> dict:
        return {
            "kill_switch_engaged": kill_switch.is_engaged(),
            "kill_switch_reason": kill_switch.reason(),
            "circuit_breaker": circuit_breaker.info(),
        }

    def base_context(request: Request, error: str | None = None, notice: str | None = None) -> dict:
        portfolio = portfolio_provider()
        usage = compute_risk_usage(portfolio, config)
        halt = halt_state()
        return {
            "request": request,
            "now": datetime.now(timezone.utc),
            "portfolio": portfolio,
            "positions": sorted(portfolio.positions.values(), key=lambda p: -abs(p.market_value)),
            "risk_usage": usage,
            "breached": [item for item in usage if item.breached],
            "pending_count": len(store.list_pending()),
            "halted": halt["kill_switch_engaged"] or halt["circuit_breaker"] is not None,
            "account_is_placeholder": config.account.is_placeholder,
            "operator_name": default_operator_name,
            "execution_status": execution_status(),
            "disengage_phrase": DISENGAGE_PHRASE,
            "error": error,
            "notice": notice,
            **halt,
        }

    def render(name: str, request: Request, extra: dict | None = None, **kwargs):
        context = base_context(request, **kwargs)
        context.update(extra or {})
        return templates.TemplateResponse(request, name, context)

    # ---- access control -------------------------------------------------

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        if not access_policy.required or request.url.path in ("/login", "/health"):
            return await call_next(request)
        if access_policy.matches(request.cookies.get(SESSION_COOKIE)):
            return await call_next(request)
        if access_policy.matches(request.headers.get("x-tradebot-token")):
            return await call_next(request)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})

    @app.post("/login")
    def login(request: Request, token: str = Form(...)):
        if not access_policy.matches(token):
            return templates.TemplateResponse(
                request, "login.html", {"request": request, "error": "Incorrect token."}
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict")
        return response

    @app.get("/health")
    def health():
        return {"ok": True}

    # ---- pages ----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        return render(
            "overview.html",
            request,
            {"recent_activity": load_activity(log_paths, limit=12)},
        )

    @app.get("/proposals", response_class=HTMLResponse)
    def proposals(request: Request):
        return render(
            "proposals.html",
            request,
            {
                "pending": store.list_pending(),
                "recent": store.list_all(limit=40),
                "allow_bulk_approve": config.approval.allow_bulk_approve,
            },
        )

    @app.get("/activity", response_class=HTMLResponse)
    def activity(request: Request, category: str = "", limit: int = 150):
        selected = {category} if category in known_categories() else None
        return render(
            "activity.html",
            request,
            {
                "events": load_activity(log_paths, limit=limit, categories=selected),
                "categories": known_categories(),
                "selected_category": category,
            },
        )

    @app.get("/controls", response_class=HTMLResponse)
    def controls(request: Request):
        return render("controls.html", request)

    # ---- proposal decisions ---------------------------------------------

    @app.post("/proposals/{proposal_id}/approve")
    def approve(request: Request, proposal_id: str, approved_by: str = Form(...)):
        try:
            proposal = store.approve(proposal_id, approved_by=approved_by)
        except (KeyError, ProposalAlreadyDecidedError, ProposalExpiredError) as exc:
            return render("proposals.html", request, _proposal_extra(store, config), error=str(exc))

        # The single path toward execution_layer, and only ever after the
        # approval above has been recorded. A failure here must surface,
        # not vanish: the human needs to know the order did not go out.
        try:
            on_approved(proposal)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the operator, never swallowed
            return render(
                "proposals.html",
                request,
                _proposal_extra(store, config),
                error=(
                    f"Approval for {proposal.symbol} was recorded, but submitting it failed: "
                    f"{type(exc).__name__}: {exc}. Check state/execution_audit.log and IBKR "
                    "before retrying -- the order may or may not have reached the broker."
                ),
            )
        return RedirectResponse("/proposals", status_code=303)

    @app.post("/proposals/{proposal_id}/reject")
    def reject(request: Request, proposal_id: str, rejected_by: str = Form(...), reason: str = Form("")):
        try:
            store.reject(proposal_id, rejected_by=rejected_by, reason=reason)
        except (KeyError, ProposalAlreadyDecidedError, ProposalExpiredError) as exc:
            return render("proposals.html", request, _proposal_extra(store, config), error=str(exc))
        return RedirectResponse("/proposals", status_code=303)

    @app.post("/proposals/bulk_approve")
    def bulk_approve(request: Request, approved_by: str = Form(...)):
        try:
            approved = store.approve_all_pending(
                approved_by=approved_by, allow_bulk=config.approval.allow_bulk_approve
            )
        except BulkApprovalDisabledError as exc:
            return render("proposals.html", request, _proposal_extra(store, config), error=str(exc))
        for proposal in approved:
            on_approved(proposal)
        return RedirectResponse("/proposals", status_code=303)

    # ---- halt controls --------------------------------------------------

    @app.post("/controls/kill-switch/engage")
    def engage_kill_switch(request: Request, engaged_by: str = Form(""), reason: str = Form("")):
        who = engaged_by.strip() or "control center"
        kill_switch.engage(f"{reason.strip() or 'engaged from control center'} (by {who})")
        return RedirectResponse("/controls", status_code=303)

    @app.post("/controls/kill-switch/disengage")
    def disengage_kill_switch(
        request: Request, disengaged_by: str = Form(...), confirm: str = Form("")
    ):
        if confirm.strip().upper() != DISENGAGE_PHRASE:
            return render(
                "controls.html",
                request,
                error=f'Type "{DISENGAGE_PHRASE}" to confirm re-enabling trading.',
            )
        kill_switch.disengage()
        return render(
            "controls.html",
            request,
            notice=f"Kill switch disengaged by {disengaged_by}. New orders can be submitted again.",
        )

    @app.post("/controls/circuit-breaker/reset")
    def reset_circuit_breaker(request: Request, cleared_by: str = Form(...), confirm: str = Form("")):
        if confirm.strip().upper() != DISENGAGE_PHRASE:
            return render(
                "controls.html",
                request,
                error=f'Type "{DISENGAGE_PHRASE}" to confirm resetting the circuit breaker.',
            )
        info = circuit_breaker.reset(cleared_by=cleared_by)
        if info is None:
            return render("controls.html", request, notice="Circuit breaker was not tripped.")
        return render(
            "controls.html",
            request,
            notice=f"Circuit breaker reset by {cleared_by}. It was tripped for: {info.get('reason')}",
        )

    # ---- json -----------------------------------------------------------

    @app.get("/api/status")
    def api_status():
        portfolio = portfolio_provider()
        usage = compute_risk_usage(portfolio, config)
        halt = halt_state()
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "equity": portfolio.equity,
            "cash": portfolio.cash,
            "daily_pnl": portfolio.daily_pnl,
            "drawdown_pct": portfolio.drawdown_pct,
            "pending_proposals": len(store.list_pending()),
            "halted": halt["kill_switch_engaged"] or halt["circuit_breaker"] is not None,
            "kill_switch_engaged": halt["kill_switch_engaged"],
            "circuit_breaker": halt["circuit_breaker"],
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "market_value": p.market_value,
                    "sector": p.sector,
                }
                for p in portfolio.positions.values()
            ],
            "risk_usage": [
                {
                    "name": item.name,
                    "used": item.used,
                    "limit": item.limit,
                    "unit": item.unit,
                    "utilization": item.utilization,
                    "breached": item.breached,
                }
                for item in usage
            ],
            "account_is_placeholder": config.account.is_placeholder,
        }

    return app


def _proposal_extra(store: ProposalStore, config) -> dict:
    return {
        "pending": store.list_pending(),
        "recent": store.list_all(limit=40),
        "allow_bulk_approve": config.approval.allow_bulk_approve,
    }
