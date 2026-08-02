from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from approval_layer.dashboard import build_app
from approval_layer.store import ProposalStore
from risk_gate.models import OrderProposal, Side


def make_order_proposal(proposal_id="p1", symbol="SPY") -> OrderProposal:
    return OrderProposal(
        proposal_id=proposal_id,
        symbol=symbol,
        side=Side.BUY,
        quantity=10,
        estimated_price=500.0,
        sector="Broad Market",
        strategy_name="momentum",
        reasoning="test reasoning",
        stop_loss_price=450.0,
    )


@pytest.fixture
def store(tmp_path) -> ProposalStore:
    return ProposalStore(tmp_path / "approvals.db")


def test_index_lists_pending_proposal(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    app = build_app(store)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "SPY" in response.text
    assert "test reasoning" in response.text


def test_approve_route_marks_approved_and_fires_callback(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    approved_callback_calls = []
    app = build_app(store, on_approved=lambda p: approved_callback_calls.append(p.id))
    client = TestClient(app)

    response = client.post("/proposals/p1/approve", data={"approved_by": "sandro"}, follow_redirects=False)
    assert response.status_code == 303
    assert store.get("p1").status.value == "APPROVED"
    assert approved_callback_calls == ["p1"]


def test_reject_route_marks_rejected(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    app = build_app(store)
    client = TestClient(app)

    response = client.post("/proposals/p1/reject", data={"rejected_by": "sandro", "reason": "no thanks"}, follow_redirects=False)
    assert response.status_code == 303
    stored = store.get("p1")
    assert stored.status.value == "REJECTED"
    assert stored.decision_note == "no thanks"


def test_approving_unknown_proposal_shows_error_inline(store):
    app = build_app(store)
    client = TestClient(app)
    response = client.post("/proposals/does-not-exist/approve", data={"approved_by": "sandro"})
    assert response.status_code == 200
    assert "no such proposal" in response.text


def test_bulk_approve_disabled_by_default_shows_error(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    app = build_app(store, allow_bulk_approve=False)
    client = TestClient(app)
    response = client.post("/proposals/bulk_approve", data={"approved_by": "sandro"})
    assert response.status_code == 200
    assert "disabled" in response.text
    assert store.get("p1").status.value == "PENDING"


def test_bulk_approve_when_enabled_fires_callback_for_each():
    import tempfile

    store = ProposalStore(f"{tempfile.mkdtemp()}/approvals.db")
    store.create(make_order_proposal(proposal_id="p1", symbol="SPY"), expiry_minutes=30)
    store.create(make_order_proposal(proposal_id="p2", symbol="QQQ"), expiry_minutes=30)

    fired = []
    app = build_app(store, allow_bulk_approve=True, on_approved=lambda p: fired.append(p.id))
    client = TestClient(app)
    response = client.post("/proposals/bulk_approve", data={"approved_by": "sandro"}, follow_redirects=False)
    assert response.status_code == 303
    assert set(fired) == {"p1", "p2"}


def test_no_bulk_approve_button_rendered_when_disabled(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    app = build_app(store, allow_bulk_approve=False)
    client = TestClient(app)
    response = client.get("/")
    assert "bulk_approve" not in response.text
