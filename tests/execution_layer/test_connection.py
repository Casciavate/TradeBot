from __future__ import annotations

import pytest

from config.schema import ConnectionConfig
from execution_layer.connection import (
    LIVE_TRADING_ENV_VAR,
    is_live_trading_enabled,
    resolve_connection_target,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(LIVE_TRADING_ENV_VAR, raising=False)


def test_defaults_to_disabled_when_env_var_unset():
    assert not is_live_trading_enabled()


def test_enabled_only_by_exact_string_true(monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV_VAR, "true")
    assert is_live_trading_enabled()


@pytest.mark.parametrize("value", ["True", "TRUE", " true ", "yes", "1", "", "false"])
def test_only_lowercase_true_variants_enable_live_trading(monkeypatch, value):
    monkeypatch.setenv(LIVE_TRADING_ENV_VAR, value)
    result = is_live_trading_enabled()
    # only exact "true" (allowing surrounding whitespace / case) should enable it;
    # ambiguous truthy-looking values like "yes"/"1" must NOT silently enable live trading
    expected = value.strip().lower() == "true"
    assert result == expected


def test_defaults_to_paper_port():
    config = ConnectionConfig(paper_port=7497, live_port=7496)
    target = resolve_connection_target(config)
    assert target.port == 7497
    assert not target.is_live


def test_live_trading_env_var_selects_live_port(monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV_VAR, "true")
    config = ConnectionConfig(paper_port=7497, live_port=7496)
    target = resolve_connection_target(config)
    assert target.port == 7496
    assert target.is_live


def test_yes_and_1_do_not_enable_live_trading(monkeypatch):
    for value in ["yes", "1", "on", "enabled"]:
        monkeypatch.setenv(LIVE_TRADING_ENV_VAR, value)
        config = ConnectionConfig(paper_port=7497, live_port=7496)
        target = resolve_connection_target(config)
        assert target.port == 7497
        assert not target.is_live
