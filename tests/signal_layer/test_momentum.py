from __future__ import annotations

import pandas as pd

from signal_layer.momentum import generate_signals
from signal_layer.models import Side


def make_df(closes: list[float], sector: str = "Broad Market") -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1_000_000] * len(closes)},
        index=dates,
    )
    df.attrs["sector"] = sector
    return df


PARAMS = {"lookback_days": 20, "skip_recent_days": 0, "top_n": 2, "stop_loss_pct": 0.10}


def test_ranks_by_return_and_picks_top_n():
    strong = make_df([100.0 + i * 2 for i in range(21)])  # strong uptrend
    weak = make_df([100.0 + i * 0.2 for i in range(21)])  # weak uptrend
    negative = make_df([100.0 - i for i in range(21)])  # downtrend

    signals = generate_signals({"STRONG": strong, "WEAK": weak, "NEG": negative}, PARAMS)

    symbols = {s.symbol for s in signals}
    assert symbols == {"STRONG", "WEAK"}
    assert all(s.side == Side.BUY for s in signals)


def test_excludes_negative_momentum_even_if_in_top_n():
    flat_down = make_df([100.0 - i * 0.5 for i in range(21)])
    signals = generate_signals({"ONLY": flat_down}, {**PARAMS, "top_n": 5})
    assert signals == []


def test_stop_loss_computed_from_entry_price():
    strong = make_df([100.0 + i * 2 for i in range(21)])
    signals = generate_signals({"STRONG": strong}, {**PARAMS, "top_n": 1})
    [signal] = signals
    assert signal.stop_loss_price == signal.entry_price * 0.90


def test_sector_is_read_from_dataframe_attrs():
    strong = make_df([100.0 + i * 2 for i in range(21)], sector="Tech")
    signals = generate_signals({"STRONG": strong}, {**PARAMS, "top_n": 1})
    assert signals[0].sector == "Tech"


def test_skips_symbols_with_insufficient_history():
    short_history = make_df([100.0, 101.0, 102.0])
    signals = generate_signals({"SHORT": short_history}, PARAMS)
    assert signals == []
