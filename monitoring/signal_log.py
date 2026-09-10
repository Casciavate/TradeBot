"""Structured logging of every signal generated (build spec section 8).

risk_gate already logs every pass/block decision and execution_layer logs
every order, but signals that never became proposals were previously
invisible. Recording them is what makes it possible to judge proposal
quality independently of what a human approved -- including signals that
were sized to zero shares or dropped before risk_gate ever saw them.

Typing-only import of signal_layer keeps monitoring dependency-free.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from monitoring.audit_log import AuditLog

if TYPE_CHECKING:  # pragma: no cover -- import-cycle avoidance
    from signal_layer.models import Signal


class SignalLog:
    def __init__(self, audit_log: AuditLog | None = None, state_dir: str = "state"):
        self.audit_log = audit_log or AuditLog(f"{state_dir}/signal_audit.log")

    def record(self, signal: "Signal", outcome: str = "generated", note: str = "") -> dict:
        """`outcome` describes what happened to the signal downstream:
        "generated", "sized_out" (sizing produced no tradable quantity),
        "proposed" (became a proposal risk_gate accepted), or "blocked"."""
        payload: dict[str, Any] = {
            "symbol": signal.symbol,
            "side": signal.side.value,
            "strategy_name": signal.strategy_name,
            "entry_price": signal.entry_price,
            "stop_loss_price": signal.stop_loss_price,
            "target_price": signal.target_price,
            "sector": signal.sector,
            "reasoning": signal.reasoning,
            "as_of": signal.as_of.isoformat() if signal.as_of else None,
            "outcome": outcome,
        }
        if note:
            payload["note"] = note
        return self.audit_log.write("signal_generated", payload)
