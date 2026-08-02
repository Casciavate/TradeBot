from __future__ import annotations

from datetime import datetime, timedelta, timezone

from risk_gate.rate_limiter import RateLimiter


def test_allows_up_to_the_per_minute_limit():
    limiter = RateLimiter(max_per_minute=5, max_per_hour=100)
    now = datetime.now(timezone.utc)
    results = [limiter.hit(now)[0] for _ in range(5)]
    assert all(results)


def test_blocks_beyond_the_per_minute_limit():
    limiter = RateLimiter(max_per_minute=5, max_per_hour=100)
    now = datetime.now(timezone.utc)
    for _ in range(5):
        assert limiter.hit(now)[0]
    allowed, reason = limiter.hit(now)
    assert not allowed
    assert "per minute" in reason


def test_adversarial_flood_of_1000_orders_per_second_is_blocked():
    """Simulates a runaway strategy trying to submit 1000 orders/second.
    Only the configured per-minute cap should get through; everything
    else must be blocked, and the limiter must not fall over or leak
    memory unboundedly under the flood."""
    limiter = RateLimiter(max_per_minute=5, max_per_hour=30)
    now = datetime.now(timezone.utc)

    allowed_count = 0
    blocked_count = 0
    for i in range(1000):
        # 1000 attempts within the same one-second window
        attempt_time = now + timedelta(microseconds=i)
        allowed, _ = limiter.hit(attempt_time)
        if allowed:
            allowed_count += 1
        else:
            blocked_count += 1

    assert allowed_count == 5
    assert blocked_count == 995
    # The limiter must not retain more than an hour's worth of timestamps.
    assert len(limiter._timestamps) <= 1000


def test_per_hour_limit_still_applies_after_minute_windows_roll_over():
    limiter = RateLimiter(max_per_minute=5, max_per_hour=8)
    base = datetime.now(timezone.utc)

    # Fill the per-minute cap, then move forward past a minute so the
    # per-minute window resets, but stay within the hour.
    for i in range(5):
        assert limiter.hit(base + timedelta(seconds=i))[0]

    later = base + timedelta(minutes=2)
    for i in range(3):
        assert limiter.hit(later + timedelta(seconds=i))[0]

    # 8th order this hour should be blocked by the hourly cap even though
    # the per-minute window is clear.
    allowed, reason = limiter.hit(later + timedelta(seconds=10))
    assert not allowed
    assert "per hour" in reason


def test_old_timestamps_are_pruned_after_an_hour():
    limiter = RateLimiter(max_per_minute=5, max_per_hour=5)
    base = datetime.now(timezone.utc)
    for i in range(5):
        assert limiter.hit(base + timedelta(seconds=i))[0]

    later = base + timedelta(hours=2)
    # All earlier timestamps should have aged out, so this is allowed again.
    allowed, _ = limiter.hit(later)
    assert allowed
