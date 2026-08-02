"""Local web dashboard for approving/rejecting trade proposals. This is
the one and only place a human signs off on a trade; execution_layer is
never reachable except through `on_approved` firing after a recorded
approval here."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from approval_layer.models import StoredProposal
from approval_layer.store import (
    BulkApprovalDisabledError,
    ProposalAlreadyDecidedError,
    ProposalExpiredError,
    ProposalStore,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_app(
    store: ProposalStore,
    allow_bulk_approve: bool = False,
    on_approved: Callable[[StoredProposal], None] | None = None,
    default_operator_name: str = "",
) -> FastAPI:
    app = FastAPI(title="TradeBot Approval Dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    on_approved = on_approved or (lambda proposal: None)

    def render(request: Request, error: str | None = None):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "pending": store.list_pending(),
                "recent": store.list_all(limit=25),
                "allow_bulk_approve": allow_bulk_approve,
                "operator_name": default_operator_name,
                "error": error,
            },
        )

    @app.get("/")
    def index(request: Request):
        return render(request)

    @app.post("/proposals/{proposal_id}/approve")
    def approve(request: Request, proposal_id: str, approved_by: str = Form(...)):
        try:
            proposal = store.approve(proposal_id, approved_by=approved_by)
            on_approved(proposal)
        except (KeyError, ProposalAlreadyDecidedError, ProposalExpiredError) as exc:
            return render(request, error=str(exc))
        return RedirectResponse("/", status_code=303)

    @app.post("/proposals/{proposal_id}/reject")
    def reject(request: Request, proposal_id: str, rejected_by: str = Form(...), reason: str = Form("")):
        try:
            store.reject(proposal_id, rejected_by=rejected_by, reason=reason)
        except (KeyError, ProposalAlreadyDecidedError, ProposalExpiredError) as exc:
            return render(request, error=str(exc))
        return RedirectResponse("/", status_code=303)

    @app.post("/proposals/bulk_approve")
    def bulk_approve(request: Request, approved_by: str = Form(...)):
        try:
            approved = store.approve_all_pending(approved_by=approved_by, allow_bulk=allow_bulk_approve)
        except BulkApprovalDisabledError as exc:
            return render(request, error=str(exc))
        for proposal in approved:
            on_approved(proposal)
        return RedirectResponse("/", status_code=303)

    return app
