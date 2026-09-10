from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from monitoring.alerts import AlertKind, AlertRouter, AlertSeverity
from monitoring.audit_log import AuditLog
from monitoring.daily_summary import build_daily_summary
from risk_gate.models import PortfolioState, Position

SUMMARY_DATE = date(2026, 9, 10)
TODAY = datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc)


@pytest.fixture
def portfolio() -> PortfolioState:
    return PortfolioState(
        equity=98_000,
        peak_equity=100_000,
        cash=80_000,
        positions={
            "SPY": Position("SPY", 20, 12_000, "Broad Market"),
            "GLD": Position("GLD", 30, 6_000, "Commodity"),
        },
        realized_pnl_today=-1_200,
        unrealized_pnl_today=400,
    )


def _write(log: AuditLog, event_type: str, payload: dict, when: datetime) -> None:
    """Writes a record with a controlled timestamp -- AuditLog stamps
    "now", so a summary test needs to place records on a specific day."""
    import json

    record = {"ts": when.isoformat(), "event_type": event_type, **payload}
    with open(log.path, "a") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def test_summary_reports_pnl_and_positions(tmp_path, portfolio, base_config):
    summary = build_daily_summary(portfolio, base_config, [tmp_path / "empty.log"], SUMMARY_DATE)

    assert summary.daily_pnl == pytest.approx(-800)
    assert summary.daily_pnl_pct == pytest.approx(-800 / 98_000)
    assert [p.symbol for p in summary.positions] == ["SPY", "GLD"]


def test_summary_counts_activity_from_the_audit_logs(tmp_path, portfolio, base_config):
    log = AuditLog(tmp_path / "audit.log")
    _write(log, "signal_generated", {"symbol": "SPY"}, TODAY)
    _write(log, "signal_generated", {"symbol": "QQQ"}, TODAY)
    _write(log, "risk_decision", {"approved": True}, TODAY)
    _write(log, "proposal_created", {"proposal_id": "p1"}, TODAY)
    _write(log, "proposal_approved", {"proposal_id": "p1"}, TODAY)
    _write(log, "order_submitted", {"order_id": 1}, TODAY)

    summary = build_daily_summary(portfolio, base_config, [log.path], SUMMARY_DATE)

    assert summary.event_counts["signals generated"] == 2
    assert summary.event_counts["proposals approved"] == 1
    assert summary.event_counts["orders submitted"] == 1


def test_records_from_other_days_are_excluded(tmp_path, portfolio, base_config):
    log = AuditLog(tmp_path / "audit.log")
    _write(log, "order_submitted", {"order_id": 1}, TODAY)
    _write(log, "order_submitted", {"order_id": 2}, TODAY - timedelta(days=1))

    summary = build_daily_summary(portfolio, base_config, [log.path], SUMMARY_DATE)

    assert summary.event_counts["orders submitted"] == 1


def test_blocked_reasons_are_tallied_by_check_name(tmp_path, portfolio, base_config):
    log = AuditLog(tmp_path / "audit.log")
    _write(
        log,
        "risk_decision",
        {"approved": False, "blocked_reasons": ["max_position_size: would exceed 8.0%"]},
        TODAY,
    )
    _write(
        log,
        "risk_decision",
        {"approved": False, "blocked_reasons": ["max_position_size: would exceed 8.0%"]},
        TODAY,
    )
    _write(
        log,
        "risk_decision",
        {"approved": False, "blocked_reasons": ["sector_concentration: too much Broad Market"]},
        TODAY,
    )

    summary = build_daily_summary(portfolio, base_config, [log.path], SUMMARY_DATE)

    assert summary.blocked_reasons == {"max_position_size": 2, "sector_concentration": 1}


def test_circuit_breaker_trips_are_surfaced(tmp_path, portfolio, base_config):
    router = AlertRouter(audit_log=AuditLog(tmp_path / "alerts.log"), throttle_seconds=0)
    router.alert(
        AlertKind.CIRCUIT_BREAKER_TRIPPED,
        AlertSeverity.CRITICAL,
        "Circuit breaker TRIPPED: daily loss 3.1%",
        raised_at=TODAY,
    )

    summary = build_daily_summary(portfolio, base_config, [router.audit_log.path], SUMMARY_DATE)

    assert len(summary.circuit_breaker_trips) == 1
    assert "daily loss" in summary.circuit_breaker_trips[0]["summary"]
    assert "circuit_breaker_cli.py reset" in summary.render_text()


def test_summary_reads_multiple_log_files(tmp_path, portfolio, base_config):
    risk_log = AuditLog(tmp_path / "risk.log")
    execution_log = AuditLog(tmp_path / "execution.log")
    _write(risk_log, "risk_decision", {"approved": True}, TODAY)
    _write(execution_log, "order_submitted", {"order_id": 1}, TODAY)

    summary = build_daily_summary(
        portfolio, base_config, [risk_log.path, execution_log.path], SUMMARY_DATE
    )

    assert summary.event_counts["risk_gate decisions"] == 1
    assert summary.event_counts["orders submitted"] == 1


def test_missing_log_file_is_not_an_error(tmp_path, portfolio, base_config):
    summary = build_daily_summary(
        portfolio, base_config, [tmp_path / "does_not_exist.log"], SUMMARY_DATE
    )

    assert summary.event_counts == {}


def test_rendered_text_includes_pnl_positions_risk_usage_and_placeholder_warning(
    tmp_path, portfolio, base_config
):
    text = build_daily_summary(
        portfolio, base_config, [tmp_path / "empty.log"], SUMMARY_DATE
    ).render_text()

    assert "TradeBot daily summary -- 2026-09-10" in text
    assert "$-800.00" in text
    assert "SPY" in text
    assert "largest position" in text
    # base_config fixture has is_placeholder=True
    assert "placeholder" in text


def test_flat_portfolio_renders_without_positions(tmp_path, flat_portfolio, base_config):
    text = build_daily_summary(
        flat_portfolio, base_config, [tmp_path / "empty.log"], SUMMARY_DATE
    ).render_text()

    assert "(flat)" in text
