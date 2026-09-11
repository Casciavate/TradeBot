"""Unified activity feed built from the append-only audit logs.

Each log is written by a different layer and none of them knows about the
others, so this module is the only place that merges them into one
timeline. It is read-only: it opens the logs, never writes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from monitoring.audit_log import AuditLog


@dataclass(frozen=True)
class ActivityEvent:
    at: datetime
    category: str
    severity: str
    summary: str
    raw: dict

    @property
    def display_time(self) -> str:
        return self.at.strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _describe(record: dict) -> tuple[str, str, str] | None:
    """(category, severity, summary) for one audit record, or None to
    leave it out of the feed."""
    event = record.get("event_type", "")

    if event == "signal_generated":
        outcome = record.get("outcome", "generated")
        return (
            "signal",
            "info",
            f"{record.get('strategy_name', '?')} signal: "
            f"{record.get('side', '?')} {record.get('symbol', '?')} ({outcome})",
        )

    if event == "risk_decision":
        if record.get("approved"):
            return (
                "risk",
                "ok",
                f"risk_gate passed {record.get('side', '?')} {record.get('symbol', '?')} "
                f"({_money(record.get('notional_usd', 0))})",
            )
        reasons = "; ".join(str(r) for r in record.get("blocked_reasons", []))
        return ("risk", "warn", f"risk_gate BLOCKED {record.get('symbol', '?')}: {reasons}")

    if event == "proposal_created":
        return ("proposal", "info", f"proposal queued: {record.get('symbol', '?')}")

    if event == "proposal_approved":
        return (
            "proposal",
            "ok",
            f"APPROVED {record.get('symbol', '?')} by {record.get('approved_by', '?')}",
        )

    if event == "proposal_rejected":
        note = record.get("reason") or ""
        suffix = f" ({note})" if note else ""
        return (
            "proposal",
            "warn",
            f"rejected {record.get('symbol', '?')} by {record.get('rejected_by', '?')}{suffix}",
        )

    if event == "proposal_expired":
        return ("proposal", "muted", f"expired unapproved: {record.get('symbol', '?')}")

    if event == "bulk_proposal_approval":
        return (
            "proposal",
            "warn",
            f"BULK approval of {record.get('count', 0)} proposals by {record.get('approved_by', '?')}",
        )

    if event == "order_submitted":
        return (
            "order",
            "ok",
            f"order sent: {record.get('side', '?')} {record.get('quantity', '?')} "
            f"{record.get('symbol', '?')} @ limit {_money(record.get('limit_price', 0))}",
        )

    if event == "order_state_updated":
        state = record.get("state", "?")
        severity = "crit" if state == "REJECTED" else "info"
        return ("order", severity, f"order {record.get('order_id', '?')} -> {state}")

    if event == "order_submit_failed":
        return ("order", "crit", f"order submission FAILED for {record.get('symbol', '?')}")

    if event == "alert":
        severity = {"CRITICAL": "crit", "WARNING": "warn"}.get(record.get("severity", ""), "info")
        return ("alert", severity, record.get("summary", "alert"))

    if event == "alert_channel_failed":
        return (
            "alert",
            "warn",
            f"alert channel {record.get('channel', '?')} failed: {record.get('error', '')}",
        )

    if event == "config_change":
        return ("config", "warn", f"config changed: {record.get('section', '?')}")

    return None


def load_activity(
    log_paths: Iterable[str | Path],
    limit: int = 100,
    categories: set[str] | None = None,
) -> list[ActivityEvent]:
    """Newest first. Records the feed has no description for are skipped
    rather than rendered as raw JSON."""
    events: list[ActivityEvent] = []

    for path in log_paths:
        for record in AuditLog(path).read_all():
            described = _describe(record)
            if described is None:
                continue
            at = _parse_ts(record.get("ts"))
            if at is None:
                continue
            category, severity, summary = described
            if categories and category not in categories:
                continue
            events.append(ActivityEvent(at, category, severity, summary, record))

    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]


def known_categories() -> list[str]:
    return ["signal", "risk", "proposal", "order", "alert", "config"]
