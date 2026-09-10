"""Reuses the risk_gate fixtures so monitoring is tested against exactly
the same config and portfolio shapes risk_gate enforces against -- if the
two ever drift, that is a bug worth failing on."""
from __future__ import annotations

from tests.risk_gate.conftest import (  # noqa: F401 -- re-exported as fixtures
    base_config,
    circuit_breaker,
    flat_portfolio,
    kill_switch,
)
