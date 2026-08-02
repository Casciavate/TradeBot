"""Pure, mechanical exit-condition checks applied to an already-open
position. No discretion: an open position is closed the moment any one of
these returns True. Each strategy's docstring says which of these apply to
it."""
from __future__ import annotations

from datetime import date, datetime

from signal_layer.models import Side


def check_stop_loss(side: Side, current_price: float, stop_loss_price: float) -> bool:
    if side == Side.BUY:
        return current_price <= stop_loss_price
    return current_price >= stop_loss_price


def check_target(side: Side, current_price: float, target_price: float | None) -> bool:
    if target_price is None:
        return False
    if side == Side.BUY:
        return current_price >= target_price
    return current_price <= target_price


def check_time_stop(entry_date: date | datetime, current_date: date | datetime, max_hold_days: int) -> bool:
    return (current_date - entry_date).days >= max_hold_days


def check_mean_reversion_exit(current_zscore: float, exit_zscore: float) -> bool:
    return current_zscore >= exit_zscore


def check_breakout_failure(current_close: float, breakout_level: float) -> bool:
    return current_close < breakout_level
