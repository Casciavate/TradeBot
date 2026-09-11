"""The approval path is the security boundary of the whole system, so
these tests are about what the UI can and cannot cause to happen."""
from __future__ import annotations

from fastapi.testclient import TestClient

from approval_layer.models import ProposalStatus
from tests.control_center.conftest import make_proposal


def test_approving_records_the_decision_and_fires_the_callback(app_factory, store):
    submitted = []
    client = TestClient(app_factory(on_approved=submitted.append))
    store.create(make_proposal(), expiry_minutes=30)

    response = client.post("/proposals/p1/approve", data={"approved_by": "sandro"})

    assert response.status_code == 200
    stored = store.get("p1")
    assert stored.status is ProposalStatus.APPROVED
    assert stored.decided_by == "sandro"
    assert [p.id for p in submitted] == ["p1"]


def test_the_callback_only_fires_after_the_approval_is_recorded(app_factory, store):
    """If the order were placed before the decision were written, a crash
    in between would leave an order with no audit record."""
    seen_status = []
    client = TestClient(app_factory(on_approved=lambda p: seen_status.append(store.get(p.id).status)))
    store.create(make_proposal(), expiry_minutes=30)

    client.post("/proposals/p1/approve", data={"approved_by": "sandro"})

    assert seen_status == [ProposalStatus.APPROVED]


def test_rejecting_records_the_decision_and_never_fires_the_callback(app_factory, store):
    submitted = []
    client = TestClient(app_factory(on_approved=submitted.append))
    store.create(make_proposal(), expiry_minutes=30)

    client.post("/proposals/p1/reject", data={"rejected_by": "sandro", "reason": "too extended"})

    assert store.get("p1").status is ProposalStatus.REJECTED
    assert submitted == []


def test_approving_twice_is_reported_not_double_submitted(app_factory, store):
    submitted = []
    client = TestClient(app_factory(on_approved=submitted.append))
    store.create(make_proposal(), expiry_minutes=30)

    client.post("/proposals/p1/approve", data={"approved_by": "sandro"})
    response = client.post("/proposals/p1/approve", data={"approved_by": "sandro"})

    assert "already APPROVED" in response.text
    assert len(submitted) == 1, "a double click must not place two orders"


def test_approving_an_expired_proposal_is_refused(app_factory, store):
    submitted = []
    client = TestClient(app_factory(on_approved=submitted.append))
    store.create(make_proposal(), expiry_minutes=-1)

    response = client.post("/proposals/p1/approve", data={"approved_by": "sandro"})

    assert "expired" in response.text
    assert submitted == []


def test_a_failing_submission_is_surfaced_not_swallowed(app_factory, store):
    """The operator has to know the order did not go out."""

    def broken(proposal):
        raise ConnectionError("gateway went away")

    client = TestClient(app_factory(on_approved=broken))
    store.create(make_proposal(), expiry_minutes=30)

    response = client.post("/proposals/p1/approve", data={"approved_by": "sandro"})

    assert response.status_code == 200
    assert "submitting it failed" in response.text
    assert "gateway went away" in response.text
    assert store.get("p1").status is ProposalStatus.APPROVED, (
        "the human's decision still happened and must stay on the record"
    )


def test_bulk_approve_is_refused_while_disabled_by_config(app_factory, store):
    submitted = []
    client = TestClient(app_factory(on_approved=submitted.append))
    store.create(make_proposal(), expiry_minutes=30)

    response = client.post("/proposals/bulk_approve", data={"approved_by": "sandro"})

    assert "bulk approval is disabled" in response.text
    assert submitted == []


def test_the_ui_cannot_reach_execution_layer_on_its_own(client, store):
    """With no callback injected, approving records the decision and
    reaches nothing -- the UI has no order-submission code of its own."""
    store.create(make_proposal(), expiry_minutes=30)

    client.post("/proposals/p1/approve", data={"approved_by": "sandro"})

    assert store.get("p1").status is ProposalStatus.APPROVED
