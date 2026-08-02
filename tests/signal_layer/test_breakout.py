from __future__ import annotations

import pytest
import pandas as pd

from signal_layer.breakout import generate_signals


PARAMS = {
    "lookback_days": 10,
    "volume_confirmation_multiple": 1.5,
    "volume_avg_days": 10,
    "stop_loss_atr_multiple": 2.0,
    "atr_days": 10,
}


def make_breakout_df(breakout_volume_multiple: float = 2.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=11, freq="D")
    closes = [100.0] * 10 + [110.0]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    volumes = [1_000_000] * 10 + [1_000_000 * breakout_volume_multiple]
    df = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=dates)
    df.attrs["sector"] = "Broad Market"
    return df


def test_enters_on_breakout_with_volume_confirmation():
    df = make_breakout_df(breakout_volume_multiple=2.0)
    signals = generate_signals({"BRK": df}, PARAMS)
    assert len(signals) == 1
    assert signals[0].symbol == "BRK"
    assert signals[0].entry_price == 110.0


def test_stop_loss_is_atr_based():
    df = make_breakout_df(breakout_volume_multiple=2.0)
    [signal] = generate_signals({"BRK": df}, PARAMS)
    assert signal.stop_loss_price == pytest.approx(110.0 - 2.0 * 2.9, rel=1e-6)


def test_no_signal_without_volume_confirmation():
    df = make_breakout_df(breakout_volume_multiple=1.1)  # below 1.5x threshold
    signals = generate_signals({"BRK": df}, PARAMS)
    assert signals == []


def test_no_signal_without_price_breakout():
    dates = pd.date_range("2024-01-01", periods=11, freq="D")
    closes = [100.0] * 11  # flat, never breaks its own trailing high
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1_000_000] * 11},
        index=dates,
    )
    df.attrs["sector"] = "Broad Market"
    signals = generate_signals({"FLAT": df}, PARAMS)
    assert signals == []
