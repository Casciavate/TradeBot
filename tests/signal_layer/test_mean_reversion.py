from __future__ import annotations

import pandas as pd
import pytest

from signal_layer.mean_reversion import generate_signals
from signal_layer.models import Side


def make_df(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [500_000] * len(closes)},
        index=dates,
    )
    df.attrs["sector"] = "Broad Market"
    return df


PARAMS = {"lookback_days": 20, "entry_zscore": -2.0, "exit_zscore": 0.0, "stop_loss_pct": 0.07, "max_hold_days": 10}


def test_enters_on_deep_dip():
    closes = [100.0] * 20 + [80.0]
    signals = generate_signals({"DIP": make_df(closes)}, PARAMS)
    assert len(signals) == 1
    assert signals[0].side == Side.BUY
    assert signals[0].symbol == "DIP"


def test_does_not_enter_within_normal_range():
    closes = [100.0 + (i % 3) for i in range(21)]
    signals = generate_signals({"CALM": make_df(closes)}, PARAMS)
    assert signals == []


def test_stop_loss_below_entry_by_configured_pct():
    closes = [100.0] * 20 + [80.0]
    signals = generate_signals({"DIP": make_df(closes)}, PARAMS)
    [signal] = signals
    assert signal.stop_loss_price == pytest.approx(signal.entry_price * 0.93)


def test_multiple_symbols_independently_evaluated():
    dip = make_df([100.0] * 20 + [80.0])
    calm = make_df([100.0 + (i % 2) for i in range(21)])
    signals = generate_signals({"DIP": dip, "CALM": calm}, PARAMS)
    assert {s.symbol for s in signals} == {"DIP"}
