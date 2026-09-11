"""The access-control boundary: loopback needs no token, anything else
requires one and refuses to start without it."""
from __future__ import annotations

import pytest

from control_center.auth import (
    AccessPolicy,
    InsecureBindError,
    generate_token,
    is_loopback,
    resolve_access_policy,
)


class TestIsLoopback:
    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST"])
    def test_recognized_loopback_hosts(self, host):
        assert is_loopback(host)

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", ""])
    def test_non_loopback_hosts(self, host):
        assert not is_loopback(host)


class TestResolveAccessPolicy:
    def test_loopback_with_no_token_set_requires_nothing(self, monkeypatch):
        monkeypatch.delenv("TRADEBOT_UI_TOKEN", raising=False)

        policy = resolve_access_policy("127.0.0.1", "TRADEBOT_UI_TOKEN")

        assert not policy.required
        assert policy.matches(None)
        assert policy.matches("anything")

    def test_loopback_with_a_token_set_still_honours_it(self, monkeypatch):
        monkeypatch.setenv("TRADEBOT_UI_TOKEN", "secret123")

        policy = resolve_access_policy("127.0.0.1", "TRADEBOT_UI_TOKEN")

        assert policy.required
        assert policy.matches("secret123")
        assert not policy.matches("wrong")

    def test_non_loopback_with_no_token_refuses_to_start(self, monkeypatch):
        monkeypatch.delenv("TRADEBOT_UI_TOKEN", raising=False)

        with pytest.raises(InsecureBindError, match="TRADEBOT_UI_TOKEN"):
            resolve_access_policy("0.0.0.0", "TRADEBOT_UI_TOKEN")

    def test_non_loopback_with_a_token_is_allowed(self, monkeypatch):
        monkeypatch.setenv("TRADEBOT_UI_TOKEN", "secret123")

        policy = resolve_access_policy("0.0.0.0", "TRADEBOT_UI_TOKEN")

        assert policy.required
        assert policy.matches("secret123")


class TestAccessPolicyMatching:
    def test_wrong_token_is_rejected(self):
        policy = AccessPolicy(required=True, token="right")
        assert not policy.matches("wrong")

    def test_missing_presented_token_is_rejected(self):
        policy = AccessPolicy(required=True, token="right")
        assert not policy.matches(None)

    def test_a_policy_with_no_stored_token_rejects_everything_when_required(self):
        """Defensive: required=True with token=None must never validate."""
        policy = AccessPolicy(required=True, token=None)
        assert not policy.matches("anything")
        assert not policy.matches(None)


def test_generate_token_produces_distinct_url_safe_values():
    a, b = generate_token(), generate_token()
    assert a != b
    assert len(a) > 20
