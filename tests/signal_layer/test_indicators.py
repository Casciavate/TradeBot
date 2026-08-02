from __future__ import annotations

import math

import pandas as pd

from signal_layer.indicators import (
    average_true_range,
    average_volume,
    rolling_high,
    rolling_zscore,
    total_return,
)


def make_close_series(values: list[float]) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=dates)


def test_total_return_basic():
    close = make_close_series([100.0] * 10 + [110.0])
    ret = total_return(close, lookback_days=10, skip_recent_days=0)
    assert math.isclose(ret, 0.10, rel_tol=1e-6)


def test_total_return_with_skip_recent_days():
    # last 3 days are a sharp reversal that should be excluded from the
    # momentum calculation via skip_recent_days.
    close = make_close_series([100.0] * 10 + [120.0, 90.0, 80.0, 70.0])
    ret = total_return(close, lookback_days=10, skip_recent_days=3)
    assert math.isclose(ret, 0.20, rel_tol=1e-6)


def test_total_return_insufficient_history_is_nan():
    close = make_close_series([100.0, 101.0])
    assert math.isnan(total_return(close, lookback_days=10))


def test_rolling_zscore_flags_deep_dip():
    values = [100.0] * 20 + [80.0]
    close = make_close_series(values)
    z = rolling_zscore(close, lookback_days=20)
    assert z < -2.0


def test_rolling_zscore_flat_series_is_nan():
    close = make_close_series([100.0] * 21)
    assert math.isnan(rolling_zscore(close, lookback_days=20))


def test_rolling_high_excludes_last_bar_by_default():
    close = make_close_series([100.0, 101.0, 102.0, 103.0, 200.0])
    high = rolling_high(close, lookback_days=4)
    assert high == 103.0


def test_average_volume_excludes_last_bar():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    volume = pd.Series([1000, 1000, 1000, 1000, 9000], index=dates)
    avg = average_volume(volume, lookback_days=4)
    assert avg == 1000


def test_average_true_range_positive_for_moving_series():
    dates = pd.date_range("2024-01-01", periods=16, freq="D")
    df = pd.DataFrame(
        {
            "high": [100 + i for i in range(16)],
            "low": [95 + i for i in range(16)],
            "close": [98 + i for i in range(16)],
        },
        index=dates,
    )
    atr = average_true_range(df, lookback_days=14)
    assert atr > 0
