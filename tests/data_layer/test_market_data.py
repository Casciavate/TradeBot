from __future__ import annotations

import pandas as pd
import pytest

from data_layer.market_data import CSVMarketDataProvider


@pytest.fixture
def csv_provider(tmp_path) -> CSVMarketDataProvider:
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "volume": [1_000_000] * 5,
        }
    )
    df.to_csv(tmp_path / "SPY.csv", index=False)
    return CSVMarketDataProvider(tmp_path)


def test_reads_bars_sorted_by_date(csv_provider):
    df = csv_provider.get_historical_bars("SPY")
    assert list(df["close"]) == [100.5, 101.5, 102.5, 103.5, 104.5]
    assert df.index.is_monotonic_increasing


def test_latest_price_is_last_close(csv_provider):
    assert csv_provider.get_latest_price("SPY") == 104.5


def test_missing_symbol_raises(csv_provider):
    with pytest.raises(FileNotFoundError):
        csv_provider.get_historical_bars("NOPE")


def test_missing_columns_raise(tmp_path):
    pd.DataFrame({"date": ["2024-01-01"], "close": [1.0]}).to_csv(tmp_path / "BAD.csv", index=False)
    provider = CSVMarketDataProvider(tmp_path)
    with pytest.raises(ValueError):
        provider.get_historical_bars("BAD")
