from __future__ import annotations

from tests.control_center.conftest import make_proposal


def test_overview_shows_equity_pnl_and_positions(client):
    body = client.get("/").text

    assert "Overview" in body
    assert "100,000" in body
    assert "SPY" in body
    assert "Risk limit headroom" in body

def test_overview_reports_all_clear_when_nothing_is_halted(client):
    assert "Trading not halted" in client.get("/").text

def test_every_page_renders(client):
    for path in ("/", "/proposals", "/activity", "/controls"):
        response = client.get(path)
        assert response.status_code == 200, path

def test_pending_proposal_appears_with_its_reasoning(client, store, base_config):
    store.create(make_proposal(), expiry_minutes=30)

    body = client.get("/proposals").text

    assert "momentum rank 2 of 40" in body
    assert "Approve" in body

def test_nav_shows_the_pending_count(client, store):
    store.create(make_proposal(proposal_id="p1"), expiry_minutes=30)
    store.create(make_proposal(proposal_id="p2", symbol="QQQ"), expiry_minutes=30)

    assert "Proposals (2)" in client.get("/").text

def test_bulk_approve_is_absent_when_disabled_by_config(client, store):
    store.create(make_proposal(), expiry_minutes=30)

    assert "Approve ALL pending" not in client.get("/proposals").text

def test_placeholder_account_size_is_called_out(client):
    assert "Placeholder account size" in client.get("/").text

def test_api_status_exposes_the_key_numbers(client, store):
    store.create(make_proposal(), expiry_minutes=30)

    payload = client.get("/api/status").json()

    assert payload["equity"] == 100_000
    assert payload["daily_pnl"] == -150
    assert payload["pending_proposals"] == 1
    assert payload["halted"] is False
    assert payload["positions"][0]["symbol"] == "SPY"

def test_activity_feed_shows_recorded_events(client, store):
    store.create(make_proposal(), expiry_minutes=30)
    store.reject("p1", rejected_by="operator", reason="too extended")

    body = client.get("/activity").text

    assert "proposal queued" in body
    assert "rejected SPY by operator" in body

def test_activity_feed_can_be_filtered_by_category(client, store, alert_router):
    from monitoring.alerts import AlertKind, AlertSeverity

    store.create(make_proposal(), expiry_minutes=30)
    alert_router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "Order REJECTED by IBKR")

    only_alerts = client.get("/activity?category=alert").text

    assert "Order REJECTED by IBKR" in only_alerts
    assert "proposal queued" not in only_alerts
