"""Real-time alerting (build spec section 8).

Design constraints that are not negotiable here:

1. **An alert channel failing must never break the thing that raised the
   alert.** If SMTP times out while the kill switch is being engaged, the
   kill switch still engages. Every channel send is wrapped; a failing
   channel is recorded to the audit log and otherwise ignored.
2. **Every alert is always written to the audit log**, regardless of which
   optional channels are configured. The audit log is the durable record;
   email/console are conveniences on top of it.
3. **Throttling is per (kind, dedup_key)**, so a connection-loss check that
   runs every cycle raises one alert, not one per cycle. Throttling never
   suppresses the audit-log write -- only the outbound channels.

This module deliberately imports nothing from risk_gate, execution_layer,
or signal_layer, so any of them can depend on it without a cycle.
"""
from __future__ import annotations

import os
import smtplib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from enum import Enum
from typing import Any, Protocol

from monitoring.audit_log import AuditLog


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertKind(str, Enum):
    """The section-8 alert surface. CRITICAL kinds are the four the build
    spec names explicitly: circuit breaker trips, connection loss, order
    rejection, kill switch activation."""

    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    CIRCUIT_BREAKER_RESET = "circuit_breaker_reset"
    KILL_SWITCH_ENGAGED = "kill_switch_engaged"
    KILL_SWITCH_DISENGAGED = "kill_switch_disengaged"
    BROKER_CONNECTION_LOST = "broker_connection_lost"
    BROKER_CONNECTION_RESTORED = "broker_connection_restored"
    ORDER_REJECTED = "order_rejected"
    ORDER_SUBMIT_FAILED = "order_submit_failed"
    POSITION_RECONCILIATION_MISMATCH = "position_reconciliation_mismatch"
    RISK_LIMIT_BREACHED = "risk_limit_breached"
    DAILY_SUMMARY = "daily_summary"


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    severity: AlertSeverity
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    dedup_key: str = ""
    raised_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def throttle_key(self) -> tuple[str, str]:
        return (self.kind.value, self.dedup_key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "summary": self.summary,
            "details": self.details,
            "dedup_key": self.dedup_key,
            "raised_at": self.raised_at.isoformat(),
        }

    def render_text(self) -> str:
        lines = [
            f"[{self.severity.value}] {self.summary}",
            f"kind: {self.kind.value}",
            f"raised_at: {self.raised_at.isoformat()}",
        ]
        if self.details:
            lines.append("")
            for key, value in sorted(self.details.items()):
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)


class AlertChannel(Protocol):
    """Anything that can deliver an alert somewhere a human will see it."""

    name: str

    def send(self, alert: Alert) -> None: ...


class ConsoleAlertChannel:
    """Prints to stdout. Useful when the pipeline is run interactively and
    as a zero-configuration default so alerting is never silently off."""

    name = "console"

    def __init__(self, stream=None):
        self._stream = stream

    def send(self, alert: Alert) -> None:
        import sys

        stream = self._stream or sys.stdout
        stream.write(alert.render_text() + "\n")
        stream.flush()


class EmailAlertChannel:
    """SMTP via the standard library. The password is read from an
    environment variable at send time and is never stored in config/ or
    written to the audit log."""

    name = "email"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        recipients: list[str],
        username: str | None = None,
        password_env_var: str = "TRADEBOT_SMTP_PASSWORD",
        use_starttls: bool = True,
        timeout_seconds: float = 10.0,
        min_severity: AlertSeverity = AlertSeverity.WARNING,
    ):
        self.host = host
        self.port = port
        self.sender = sender
        self.recipients = recipients
        self.username = username
        self.password_env_var = password_env_var
        self.use_starttls = use_starttls
        self.timeout_seconds = timeout_seconds
        self.min_severity = min_severity

    def _should_send(self, alert: Alert) -> bool:
        order = {AlertSeverity.INFO: 0, AlertSeverity.WARNING: 1, AlertSeverity.CRITICAL: 2}
        return order[alert.severity] >= order[self.min_severity]

    def build_message(self, alert: Alert) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = f"[TradeBot {alert.severity.value}] {alert.summary}"
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(alert.render_text())
        return message

    def send(self, alert: Alert) -> None:
        if not self._should_send(alert):
            return
        if not self.recipients:
            raise ValueError("EmailAlertChannel has no recipients configured")

        message = self.build_message(alert)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
            if self.use_starttls:
                smtp.starttls()
            if self.username:
                password = os.environ.get(self.password_env_var)
                if not password:
                    raise RuntimeError(
                        f"SMTP username is set but ${self.password_env_var} is empty -- "
                        "cannot authenticate to send the alert"
                    )
                smtp.login(self.username, password)
            smtp.send_message(message)


class AlertRouter:
    """Fans an alert out to every configured channel. Always writes to the
    audit log first, so the durable record exists even if every channel
    fails."""

    def __init__(
        self,
        audit_log: AuditLog | None = None,
        channels: list[AlertChannel] | None = None,
        throttle_seconds: float = 300.0,
        state_dir: str = "state",
    ):
        self.audit_log = audit_log or AuditLog(f"{state_dir}/alerts.log")
        self.channels: list[AlertChannel] = list(channels or [])
        self.throttle_seconds = throttle_seconds
        self._last_sent: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()

    def _is_throttled(self, alert: Alert) -> bool:
        if self.throttle_seconds <= 0:
            return False
        window = timedelta(seconds=self.throttle_seconds)
        with self._lock:
            last = self._last_sent.get(alert.throttle_key)
            if last is not None and alert.raised_at - last < window:
                return True
            self._last_sent[alert.throttle_key] = alert.raised_at
        return False

    def raise_alert(self, alert: Alert) -> Alert:
        self.audit_log.write("alert", alert.as_dict(), ts=alert.raised_at)

        if self._is_throttled(alert):
            self.audit_log.write(
                "alert_throttled",
                {"kind": alert.kind.value, "dedup_key": alert.dedup_key},
            )
            return alert

        for channel in self.channels:
            try:
                channel.send(alert)
            except Exception as exc:  # noqa: BLE001 -- a broken channel must never propagate
                self.audit_log.write(
                    "alert_channel_failed",
                    {
                        "channel": getattr(channel, "name", channel.__class__.__name__),
                        "kind": alert.kind.value,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
        return alert

    def alert(
        self,
        kind: AlertKind,
        severity: AlertSeverity,
        summary: str,
        details: dict[str, Any] | None = None,
        dedup_key: str = "",
        raised_at: datetime | None = None,
    ) -> Alert:
        alert = Alert(
            kind=kind,
            severity=severity,
            summary=summary,
            details=details or {},
            dedup_key=dedup_key,
            raised_at=raised_at or datetime.now(timezone.utc),
        )
        return self.raise_alert(alert)

    def recent(self, limit: int = 25) -> list[dict]:
        records = [r for r in self.audit_log.read_all() if r.get("event_type") == "alert"]
        return records[-limit:][::-1]
