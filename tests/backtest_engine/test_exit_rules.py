from __future__ import annotations

from datetime import date

import pandas as pd

from backtest_engine.exit_rules import check_exit
from backtest_engine.portfolio import OpenPosition
from risk_gate.models import Side


def make_position(strategy_name, stop_loss_price=None, target_price=None, entry_date=date(2024, 1, 1), extra=None):
    return OpenPosition(
        symbol="SPY",
        strategy_name=strategy_name,
        side=Side.BUY,
        quantity=10,
        entry_price=100.0,
        entry_date=entry_date,
        entry_cost_basis=1000.0,
        stop_loss_price=stop_loss_price,
        target_price=target_price,
        extra=extra or {},
    )


def make_flat_data(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1_000_000] * len(closes)},
        index=dates,
    )


def test_stop_loss_exit_applies_regardless_of_strategy():
    position = make_position("momentum", stop_loss_price=95.0)
    should_exit, reason = check_exit("momentum", position, date(2024, 1, 2), 90.0, make_flat_data([100.0]), {})
    assert should_exit
    assert reason == "stop_loss"


def test_momentum_no_exit_without_stop_loss_breach():
    position = make_position("momentum", stop_loss_price=90.0)
    should_exit, _ = check_exit("momentum", position, date(2024, 1, 2), 99.0, make_flat_data([99.0]), {})
    assert not should_exit


def test_mean_reversion_exits_on_zscore_reversion():
    position = make_position("mean_reversion", stop_loss_price=80.0)
    closes = [100.0] * 20 + [80.0] * 5 + [101.0]  # reverted back above the mean
    df = make_flat_data(closes)
    params = {"lookback_days": 20, "exit_zscore": 0.0, "max_hold_days": 30}
    should_exit, reason = check_exit("mean_reversion", position, date(2024, 2, 1), 101.0, df, params)
    assert should_exit
    assert reason == "mean_reversion_exit"


def test_mean_reversion_exits_on_time_stop():
    position = make_position("mean_reversion", stop_loss_price=80.0, entry_date=date(2024, 1, 1))
    df = make_flat_data([90.0] * 25)
    params = {"lookback_days": 20, "exit_zscore": 0.0, "max_hold_days": 10}
    should_exit, reason = check_exit("mean_reversion", position, date(2024, 1, 15), 90.0, df, params)
    assert should_exit
    assert reason == "time_stop"


def test_breakout_exits_on_failure_below_level():
    position = make_position("breakout", stop_loss_price=80.0, extra={"breakout_level": 100.0})
    should_exit, reason = check_exit("breakout", position, date(2024, 1, 5), 99.0, make_flat_data([99.0]), {})
    assert should_exit
    assert reason == "breakout_failure"


def test_breakout_no_exit_while_above_level():
    position = make_position("breakout", stop_loss_price=80.0, extra={"breakout_level": 100.0})
    should_exit, _ = check_exit("breakout", position, date(2024, 1, 5), 105.0, make_flat_data([105.0]), {})
    assert not should_exit
