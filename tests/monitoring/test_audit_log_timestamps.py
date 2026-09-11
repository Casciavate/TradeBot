"""AuditLog.write() previously always stamped real wall-clock time and
ignored any timestamp the caller already had, which silently broke two
things: a backtest's risk_decision records all landed on the day the
backtest was *run*, not the simulated day being evaluated, and a
backdated alert's `raised_at` disagreed with the "ts" field used to file
it into a daily summary. This file guards the fix."""
from __future__ import annotations

from datetime import datetime, timezone

from monitoring.audit_log import AuditLog


def test_write_defaults_to_real_wall_clock_time(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    before = datetime.now(timezone.utc)

    record = log.write("test_event", {})

    after = datetime.now(timezone.utc)
    written = datetime.fromisoformat(record["ts"])
    assert before <= written <= after


def test_write_honours_an_explicit_timestamp(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    simulated = datetime(2020, 3, 16, 9, 30, tzinfo=timezone.utc)

    record = log.write("risk_decision", {"symbol": "SPY"}, ts=simulated)

    assert record["ts"] == simulated.isoformat()


def test_a_backtest_style_call_sequence_preserves_simulated_dates(tmp_path):
    """Exercises the exact pattern backtest_engine relies on: many writes
    for different simulated days, all issued within the same instant of
    real time."""
    log = AuditLog(tmp_path / "audit.log")
    simulated_days = [
        datetime(2019, 1, 2, tzinfo=timezone.utc),
        datetime(2019, 6, 15, tzinfo=timezone.utc),
        datetime(2020, 3, 16, tzinfo=timezone.utc),
    ]

    for day in simulated_days:
        log.write("risk_decision", {"symbol": "SPY"}, ts=day)

    recorded_dates = [datetime.fromisoformat(r["ts"]).date() for r in log.read_all()]
    assert recorded_dates == [d.date() for d in simulated_days]
