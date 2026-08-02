"""Small, pure, independently-testable indicator building blocks shared
across strategies. Every strategy's entry/exit math is expressed in terms
of these -- no strategy computes an indicator inline."""
from __future__ import annotations

import numpy as np
import pandas as pd


def total_return(close: pd.Series, lookback_days: int, skip_recent_days: int = 0) -> float:
    """Return over the window ending `skip_recent_days` before the last
    bar, spanning `lookback_days` before that. skip_recent_days > 0
    implements the classic 12-1 momentum convention of excluding the most
    recent month to avoid short-term reversal effects."""
    if len(close) < lookback_days + skip_recent_days + 1:
        return float("nan")
    end_idx = len(close) - 1 - skip_recent_days
    start_idx = end_idx - lookback_days
    start_price = close.iloc[start_idx]
    end_price = close.iloc[end_idx]
    if start_price <= 0:
        return float("nan")
    return (end_price / start_price) - 1.0


def rolling_zscore(close: pd.Series, lookback_days: int) -> float:
    if len(close) < lookback_days + 1:
        return float("nan")
    window = close.iloc[-lookback_days:]
    mean = window.mean()
    std = window.std(ddof=0)
    if std == 0 or np.isnan(std):
        return float("nan")
    return (close.iloc[-1] - mean) / std


def rolling_high(close: pd.Series, lookback_days: int, exclude_last: bool = True) -> float:
    """Highest close over the trailing window, excluding today's bar by
    default so "today breaks the N-day high" is well-defined."""
    series = close.iloc[:-1] if exclude_last else close
    if len(series) < lookback_days:
        return float("nan")
    return series.iloc[-lookback_days:].max()


def average_volume(volume: pd.Series, lookback_days: int, exclude_last: bool = True) -> float:
    series = volume.iloc[:-1] if exclude_last else volume
    if len(series) < lookback_days:
        return float("nan")
    return series.iloc[-lookback_days:].mean()


def average_true_range(df: pd.DataFrame, lookback_days: int) -> float:
    if len(df) < lookback_days + 1:
        return float("nan")
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.iloc[-lookback_days:].mean()
