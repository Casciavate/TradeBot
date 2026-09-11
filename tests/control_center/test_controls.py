"""Halting must be easy; re-enabling must be deliberate."""
from __future__ import annotations

from tests.control_center.conftest import make_proposal


def test_engaging_the_kill_switch_takes_one_click(client, kill_switch):
    client.post("/controls/kill-switch/engage", data={"engaged_by": "sandro", "reason": "spooked"})

    assert kill_switch.is_engaged()
    assert "spooked" in kill_switch.reason()
    assert "sandro" in kill_switch.reason()


def test_engaging_works_with_no_reason_given(client, kill_switch):
    client.post("/controls/kill-switch/engage", data={})

    assert kill_switch.is_engaged()


def test_engaging_raises_a_critical_alert(app_factory, kill_switch, alert_router):
    from fastapi.testclient import TestClient

    kill_switch.alert_router = alert_router
    TestClient(app_factory()).post("/controls/kill-switch/engage", data={"engaged_by": "sandro"})

    kinds = [r["kind"] for r in alert_router.audit_log.read_all() if r["event_type"] == "alert"]
    assert "kill_switch_engaged" in kinds


def test_disengaging_without_the_confirmation_phrase_is_refused(client, kill_switch):
    kill_switch.engage("halted")

    response = client.post(
        "/controls/kill-switch/disengage", data={"disengaged_by": "sandro", "confirm": "yes"}
    )

    assert kill_switch.is_engaged(), "trading must not resume on a typo"
    assert "to confirm" in response.text


def test_disengaging_with_the_confirmation_phrase_works(client, kill_switch):
    kill_switch.engage("halted")

    response = client.post(
        "/controls/kill-switch/disengage",
        data={"disengaged_by": "sandro", "confirm": "RESUME TRADING"},
    )

    assert not kill_switch.is_engaged()
    assert "disengaged by sandro" in response.text


def test_the_confirmation_phrase_is_case_insensitive(client, kill_switch):
    kill_switch.engage("halted")

    client.post(
        "/controls/kill-switch/disengage",
        data={"disengaged_by": "sandro", "confirm": "resume trading"},
    )

    assert not kill_switch.is_engaged()


def test_resetting_the_breaker_without_confirmation_is_refused(client, circuit_breaker):
    circuit_breaker.trip("daily loss 3.1%")

    response = client.post(
        "/controls/circuit-breaker/reset", data={"cleared_by": "sandro", "confirm": ""}
    )

    assert circuit_breaker.is_tripped()
    assert "to confirm" in response.text


def test_resetting_the_breaker_with_confirmation_records_who_cleared_it(client, circuit_breaker):
    circuit_breaker.trip("daily loss 3.1%")

    response = client.post(
        "/controls/circuit-breaker/reset",
        data={"cleared_by": "sandro", "confirm": "RESUME TRADING"},
    )

    assert not circuit_breaker.is_tripped()
    assert "reset by sandro" in response.text
    assert "daily loss 3.1%" in response.text


def test_a_tripped_breaker_is_shown_on_every_page(client, circuit_breaker):
    circuit_breaker.trip("drawdown 13% breached the 12.00% circuit breaker")

    for path in ("/", "/proposals", "/activity", "/controls"):
        assert "CIRCUIT BREAKER TRIPPED" in client.get(path).text, path


def test_an_engaged_kill_switch_is_shown_on_every_page(client, kill_switch):
    kill_switch.engage("manual halt")

    for path in ("/", "/proposals", "/activity", "/controls"):
        assert "KILL SWITCH ENGAGED" in client.get(path).text, path


def test_the_proposals_page_warns_while_trading_is_halted(client, kill_switch, store):
    store.create(make_proposal(), expiry_minutes=30)
    kill_switch.engage("manual halt")

    assert "Trading is halted" in client.get("/proposals").text


def test_api_status_reports_the_halt(client, kill_switch):
    kill_switch.engage("manual halt")

    payload = client.get("/api/status").json()

    assert payload["halted"] is True
    assert payload["kill_switch_engaged"] is True
