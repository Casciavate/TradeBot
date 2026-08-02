from __future__ import annotations

from datetime import date

from signal_layer.exits import (
    check_breakout_failure,
    check_mean_reversion_exit,
    check_stop_loss,
    check_target,
    check_time_stop,
)
from signal_layer.models import Side


def test_stop_loss_triggers_for_long_below_stop():
    assert check_stop_loss(Side.BUY, current_price=90.0, stop_loss_price=95.0)


def test_stop_loss_does_not_trigger_for_long_above_stop():
    assert not check_stop_loss(Side.BUY, current_price=96.0, stop_loss_price=95.0)


def test_target_none_never_triggers():
    assert not check_target(Side.BUY, current_price=1000.0, target_price=None)


def test_target_triggers_for_long_above_target():
    assert check_target(Side.BUY, current_price=110.0, target_price=105.0)


def test_time_stop_triggers_after_max_hold_days():
    assert check_time_stop(date(2024, 1, 1), date(2024, 1, 11), max_hold_days=10)
    assert not check_time_stop(date(2024, 1, 1), date(2024, 1, 5), max_hold_days=10)


def test_mean_reversion_exit_triggers_at_zero_zscore():
    assert check_mean_reversion_exit(current_zscore=0.1, exit_zscore=0.0)
    assert not check_mean_reversion_exit(current_zscore=-0.5, exit_zscore=0.0)


def test_breakout_failure_triggers_when_price_falls_back_below_level():
    assert check_breakout_failure(current_close=99.0, breakout_level=100.0)
    assert not check_breakout_failure(current_close=101.0, breakout_level=100.0)
