from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_layer.pacing import HistoricalDataPacingGuard


def test_allows_requests_under_the_window_cap():
    guard = HistoricalDataPacingGuard(max_requests_per_10_min=60)
    now = datetime.now(timezone.utc)
    for i in range(60):
        key = (f"SYM{i}", "1 day", "1 Y")
        allowed, _ = guard.check(key, now)
        assert allowed
        guard.record(key, now)


def test_blocks_the_61st_request_in_the_window():
    guard = HistoricalDataPacingGuard(max_requests_per_10_min=60)
    now = datetime.now(timezone.utc)
    for i in range(60):
        key = (f"SYM{i}", "1 day", "1 Y")
        guard.record(key, now)

    allowed, reason = guard.check(("SYM60", "1 day", "1 Y"), now)
    assert not allowed
    assert "10-minute" in reason


def test_blocks_identical_request_repeated_too_soon():
    guard = HistoricalDataPacingGuard(min_seconds_between_identical_requests=15)
    now = datetime.now(timezone.utc)
    key = ("SPY", "1 day", "1 Y")
    guard.record(key, now)

    allowed, reason = guard.check(key, now + timedelta(seconds=5))
    assert not allowed
    assert "repeated" in reason


def test_allows_identical_request_after_cooldown():
    guard = HistoricalDataPacingGuard(min_seconds_between_identical_requests=15)
    now = datetime.now(timezone.utc)
    key = ("SPY", "1 day", "1 Y")
    guard.record(key, now)

    allowed, _ = guard.check(key, now + timedelta(seconds=16))
    assert allowed


def test_window_rolls_off_after_10_minutes():
    guard = HistoricalDataPacingGuard(max_requests_per_10_min=1)
    now = datetime.now(timezone.utc)
    guard.record(("SPY", "1 day", "1 Y"), now)

    allowed, _ = guard.check(("QQQ", "1 day", "1 Y"), now + timedelta(minutes=11))
    assert allowed
