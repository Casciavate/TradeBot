from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from approval_layer.models import ProposalStatus
from approval_layer.store import (
    BulkApprovalDisabledError,
    ProposalAlreadyDecidedError,
    ProposalExpiredError,
    ProposalStore,
)
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
        target_price=None,
    )


@pytest.fixture
def store(tmp_path) -> ProposalStore:
    return ProposalStore(tmp_path / "approvals.db")


def test_create_and_get_pending(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].status == ProposalStatus.PENDING
    assert pending[0].symbol == "SPY"


def test_approve_moves_out_of_pending(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    approved = store.approve("p1", approved_by="sandro")
    assert approved.status == ProposalStatus.APPROVED
    assert approved.decided_by == "sandro"
    assert store.list_pending() == []


def test_reject_records_reason(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    rejected = store.reject("p1", rejected_by="sandro", reason="too risky")
    assert rejected.status == ProposalStatus.REJECTED
    assert rejected.decision_note == "too risky"


def test_cannot_approve_twice(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    store.approve("p1", approved_by="sandro")
    with pytest.raises(ProposalAlreadyDecidedError):
        store.approve("p1", approved_by="sandro")


def test_expired_proposal_cannot_be_approved(store):
    now = datetime.now(timezone.utc)
    store.create(make_order_proposal(), expiry_minutes=30, now=now)
    later = now + timedelta(minutes=31)
    with pytest.raises(ProposalExpiredError):
        store.approve("p1", approved_by="sandro", now=later)

    pending = store.list_pending(now=later)
    assert pending == []


def test_list_pending_auto_expires_stale_proposals(store):
    now = datetime.now(timezone.utc)
    store.create(make_order_proposal(), expiry_minutes=1, now=now)
    later = now + timedelta(minutes=5)
    assert store.list_pending(now=later) == []
    all_proposals = store.list_all()
    assert all_proposals[0].status == ProposalStatus.EXPIRED


def test_bulk_approve_disabled_by_default(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    with pytest.raises(BulkApprovalDisabledError):
        store.approve_all_pending(approved_by="sandro", allow_bulk=False)
    assert store.list_pending()[0].status == ProposalStatus.PENDING


def test_bulk_approve_when_enabled_logs_distinct_event(store):
    store.create(make_order_proposal(proposal_id="p1", symbol="SPY"), expiry_minutes=30)
    store.create(make_order_proposal(proposal_id="p2", symbol="QQQ"), expiry_minutes=30)

    approved = store.approve_all_pending(approved_by="sandro", allow_bulk=True)
    assert len(approved) == 2
    assert all(p.status == ProposalStatus.APPROVED for p in approved)

    records = store.audit_log.read_all()
    bulk_events = [r for r in records if r["event_type"] == "bulk_proposal_approval"]
    individual_events = [r for r in records if r["event_type"] == "proposal_approved"]
    assert len(bulk_events) == 1
    assert bulk_events[0]["count"] == 2
    assert individual_events == []  # bulk approval logs distinctly, not as individual approvals


def test_audit_log_records_creation_and_decision(store):
    store.create(make_order_proposal(), expiry_minutes=30)
    store.approve("p1", approved_by="sandro")
    records = store.audit_log.read_all()
    event_types = [r["event_type"] for r in records]
    assert event_types == ["proposal_created", "proposal_approved"]
