from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from monitoring.alerts import (
    Alert,
    AlertKind,
    AlertRouter,
    AlertSeverity,
    ConsoleAlertChannel,
    EmailAlertChannel,
)
from monitoring.audit_log import AuditLog


class RecordingChannel:
    name = "recording"

    def __init__(self):
        self.sent: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)


class ExplodingChannel:
    name = "exploding"

    def send(self, alert: Alert) -> None:
        raise RuntimeError("SMTP timed out")


@pytest.fixture
def router(tmp_path) -> AlertRouter:
    return AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)


def test_every_alert_is_written_to_the_audit_log(router):
    router.alert(AlertKind.KILL_SWITCH_ENGAGED, AlertSeverity.CRITICAL, "engaged")

    records = [r for r in router.audit_log.read_all() if r["event_type"] == "alert"]
    assert len(records) == 1
    assert records[0]["kind"] == "kill_switch_engaged"
    assert records[0]["severity"] == "CRITICAL"


def test_alert_reaches_every_configured_channel(router):
    first, second = RecordingChannel(), RecordingChannel()
    router.channels = [first, second]

    router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "rejected")

    assert len(first.sent) == 1
    assert len(second.sent) == 1


def test_a_failing_channel_does_not_break_the_caller_or_other_channels(router):
    """A broken alert channel must never stop the kill switch engaging or
    prevent a working channel from delivering."""
    working = RecordingChannel()
    router.channels = [ExplodingChannel(), working]

    router.alert(AlertKind.KILL_SWITCH_ENGAGED, AlertSeverity.CRITICAL, "engaged")

    assert len(working.sent) == 1
    failures = [r for r in router.audit_log.read_all() if r["event_type"] == "alert_channel_failed"]
    assert len(failures) == 1
    assert "SMTP timed out" in failures[0]["error"]


def test_repeat_alerts_within_the_throttle_window_are_not_redelivered(tmp_path):
    channel = RecordingChannel()
    router = AlertRouter(
        audit_log=AuditLog(tmp_path / "alerts.log"), channels=[channel], throttle_seconds=300
    )
    start = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)

    router.alert(AlertKind.BROKER_CONNECTION_LOST, AlertSeverity.CRITICAL, "lost", raised_at=start)
    router.alert(
        AlertKind.BROKER_CONNECTION_LOST,
        AlertSeverity.CRITICAL,
        "lost",
        raised_at=start + timedelta(seconds=30),
    )

    assert len(channel.sent) == 1


def test_throttling_never_suppresses_the_audit_log_record(tmp_path):
    channel = RecordingChannel()
    router = AlertRouter(
        audit_log=AuditLog(tmp_path / "alerts.log"), channels=[channel], throttle_seconds=300
    )
    start = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)

    router.alert(AlertKind.BROKER_CONNECTION_LOST, AlertSeverity.CRITICAL, "lost", raised_at=start)
    router.alert(
        AlertKind.BROKER_CONNECTION_LOST,
        AlertSeverity.CRITICAL,
        "lost",
        raised_at=start + timedelta(seconds=30),
    )

    alerts = [r for r in router.audit_log.read_all() if r["event_type"] == "alert"]
    assert len(alerts) == 2, "the durable record must keep both occurrences"


def test_alerts_past_the_throttle_window_are_delivered_again(tmp_path):
    channel = RecordingChannel()
    router = AlertRouter(
        audit_log=AuditLog(tmp_path / "alerts.log"), channels=[channel], throttle_seconds=300
    )
    start = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)

    router.alert(AlertKind.BROKER_CONNECTION_LOST, AlertSeverity.CRITICAL, "lost", raised_at=start)
    router.alert(
        AlertKind.BROKER_CONNECTION_LOST,
        AlertSeverity.CRITICAL,
        "lost",
        raised_at=start + timedelta(seconds=301),
    )

    assert len(channel.sent) == 2


def test_different_dedup_keys_are_throttled_independently(tmp_path):
    channel = RecordingChannel()
    router = AlertRouter(
        audit_log=AuditLog(tmp_path / "alerts.log"), channels=[channel], throttle_seconds=300
    )
    start = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)

    router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "a", dedup_key="1", raised_at=start)
    router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "b", dedup_key="2", raised_at=start)

    assert len(channel.sent) == 2


def test_console_channel_writes_rendered_alert(router):
    stream = io.StringIO()
    router.channels = [ConsoleAlertChannel(stream=stream)]

    router.alert(
        AlertKind.CIRCUIT_BREAKER_TRIPPED,
        AlertSeverity.CRITICAL,
        "Circuit breaker TRIPPED: daily loss",
        {"reason": "daily loss 3.1%"},
    )

    output = stream.getvalue()
    assert "[CRITICAL]" in output
    assert "circuit_breaker_tripped" in output
    assert "daily loss 3.1%" in output


def test_recent_returns_newest_first(router):
    router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "first")
    router.alert(AlertKind.ORDER_REJECTED, AlertSeverity.CRITICAL, "second")

    recent = router.recent()
    assert recent[0]["summary"] == "second"


class TestEmailChannel:
    def _channel(self, **kwargs):
        defaults = dict(
            host="smtp.example.com",
            port=587,
            sender="bot@example.com",
            recipients=["human@example.com"],
        )
        defaults.update(kwargs)
        return EmailAlertChannel(**defaults)

    def test_message_carries_severity_and_summary(self):
        channel = self._channel()
        alert = Alert(
            kind=AlertKind.ORDER_REJECTED,
            severity=AlertSeverity.CRITICAL,
            summary="Order REJECTED by IBKR: BUY 10 SPY",
        )

        message = channel.build_message(alert)

        assert message["Subject"] == "[TradeBot CRITICAL] Order REJECTED by IBKR: BUY 10 SPY"
        assert message["To"] == "human@example.com"
        assert "order_rejected" in message.get_content()

    def test_info_alerts_are_filtered_out_below_min_severity(self):
        channel = self._channel(min_severity=AlertSeverity.WARNING)
        alert = Alert(kind=AlertKind.DAILY_SUMMARY, severity=AlertSeverity.INFO, summary="daily")

        # send() returns without touching SMTP; an attempted connection to
        # smtp.example.com would fail loudly instead.
        channel.send(alert)

    def test_missing_password_env_var_is_reported_not_silently_skipped(self, monkeypatch):
        monkeypatch.delenv("TRADEBOT_SMTP_PASSWORD", raising=False)
        channel = self._channel(username="bot")
        alert = Alert(
            kind=AlertKind.ORDER_REJECTED, severity=AlertSeverity.CRITICAL, summary="rejected"
        )

        sent = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                pass

            def login(self, user, password):
                sent.append((user, password))

            def send_message(self, message):
                sent.append(message)

        monkeypatch.setattr("monitoring.alerts.smtplib.SMTP", FakeSMTP)

        with pytest.raises(RuntimeError, match="TRADEBOT_SMTP_PASSWORD"):
            channel.send(alert)
        assert sent == []
