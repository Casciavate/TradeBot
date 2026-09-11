"""The token check is middleware wired into build_control_center, not
just the standalone AccessPolicy -- this exercises it end to end."""
from __future__ import annotations

from fastapi.testclient import TestClient

from control_center.auth import AccessPolicy


def test_no_policy_required_serves_every_page_directly(client):
    assert client.get("/").status_code == 200
    assert client.get("/proposals").status_code == 200


def test_a_required_policy_redirects_unauthenticated_requests_to_login(app_factory):
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_is_reachable_without_a_token(app_factory):
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    assert client.get("/login").status_code == 200


def test_a_correct_token_via_header_grants_access(app_factory):
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    response = client.get("/", headers={"x-tradebot-token": "secret"})

    assert response.status_code == 200


def test_an_incorrect_token_via_header_is_refused(app_factory):
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    response = client.get("/", headers={"x-tradebot-token": "wrong"}, follow_redirects=False)

    assert response.status_code == 303


def test_logging_in_sets_a_cookie_that_grants_subsequent_access(app_factory):
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    login_response = client.post("/login", data={"token": "secret"}, follow_redirects=False)
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"

    page = client.get("/")
    assert page.status_code == 200


def test_logging_in_with_the_wrong_token_does_not_set_a_cookie(app_factory):
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    client.post("/login", data={"token": "wrong"})

    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303


def test_health_endpoint_bypasses_auth(app_factory):
    """A liveness probe must not need a token, or nothing external can
    ever check whether the process is up."""
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    assert client.get("/health").status_code == 200


def test_the_approve_endpoint_is_also_gated(app_factory, store):
    from tests.control_center.conftest import make_proposal

    store.create(make_proposal(), expiry_minutes=30)
    client = TestClient(app_factory(access_policy=AccessPolicy(required=True, token="secret")))

    response = client.post(
        "/proposals/p1/approve", data={"approved_by": "sandro"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
