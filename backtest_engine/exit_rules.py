"""Dispatches to each strategy's exit rules (signal_layer.exits) with the
strategy-specific state (breakout level, z-score lookback, hold-time
limit) needed to apply them mechanically during a simulation."""
from __future__ import annotations

import math
from datetime import date as date_type

import pandas as pd

from backtest_engine.portfolio import OpenPosition
from signal_layer.exits import (
    check_breakout_failure,
    check_mean_reversion_exit,
    check_stop_loss,
    check_target,
    check_time_stop,
)
from signal_layer.indicators import rolling_zscore


def check_exit(
    strategy_name: str,
    position: OpenPosition,
    current_date: date_type,
    current_close: float,
    data_to_date: pd.DataFrame,
    params: dict,
) -> tuple[bool, str | None]:
    if position.stop_loss_price is not None and check_stop_loss(position.side, current_close, position.stop_loss_price):
        return True, "stop_loss"
    if check_target(position.side, current_close, position.target_price):
        return True, "target"

    if strategy_name == "mean_reversion":
        z = rolling_zscore(data_to_date["close"], params["lookback_days"])
        if not math.isnan(z) and check_mean_reversion_exit(z, params["exit_zscore"]):
            return True, "mean_reversion_exit"
        if check_time_stop(position.entry_date, current_date, params["max_hold_days"]):
            return True, "time_stop"
    elif strategy_name == "breakout":
        breakout_level = position.extra.get("breakout_level")
        if breakout_level is not None and check_breakout_failure(current_close, breakout_level):
            return True, "breakout_failure"
    # momentum: no additional per-day exit beyond the stop-loss above --
    # rebalance-driven exits (dropping out of the top_n) are handled by
    # the engine itself, since they require recomputing the whole
    # cross-sectional ranking, not just this one position's state.

    return False, None
