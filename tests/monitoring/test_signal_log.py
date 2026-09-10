from __future__ import annotations

from datetime import datetime, timezone

from monitoring.audit_log import AuditLog
from monitoring.signal_log import SignalLog
from signal_layer.models import Side, Signal


def _signal(**kwargs) -> Signal:
    defaults = dict(
        symbol="SPY",
        side=Side.BUY,
        strategy_name="momentum",
        reasoning="12-month momentum rank 2 of 40",
        entry_price=500.0,
        stop_loss_price=450.0,
        sector="Broad Market",
        target_price=None,
        as_of=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Signal(**defaults)


def test_signal_is_recorded_with_its_reasoning(tmp_path):
    log = SignalLog(audit_log=AuditLog(tmp_path / "signals.log"))

    log.record(_signal())

    records = log.audit_log.read_all()
    assert len(records) == 1
    assert records[0]["event_type"] == "signal_generated"
    assert records[0]["symbol"] == "SPY"
    assert records[0]["strategy_name"] == "momentum"
    assert records[0]["reasoning"] == "12-month momentum rank 2 of 40"
    assert records[0]["outcome"] == "generated"


def test_outcome_distinguishes_signals_that_never_became_proposals(tmp_path):
    log = SignalLog(audit_log=AuditLog(tmp_path / "signals.log"))

    log.record(_signal(symbol="QQQ"), outcome="sized_out", note="0 shares at 8% cap")

    record = log.audit_log.read_all()[0]
    assert record["outcome"] == "sized_out"
    assert record["note"] == "0 shares at 8% cap"


def test_signal_without_timestamp_is_recorded(tmp_path):
    log = SignalLog(audit_log=AuditLog(tmp_path / "signals.log"))

    log.record(_signal(as_of=None))

    assert log.audit_log.read_all()[0]["as_of"] is None
