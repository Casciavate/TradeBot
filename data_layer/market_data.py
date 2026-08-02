"""Market data provider interface. signal_layer and backtest_engine only
ever depend on the MarketDataProvider protocol and consume a plain
dict[symbol -> pandas.DataFrame] of OHLCV bars -- they never talk to IBKR
directly. Unit tests use CSVMarketDataProvider (or synthetic DataFrames)
exclusively; IBKRMarketDataProvider requires a live TWS/Gateway connection
and is exercised only via scripts/collect_market_data.py against paper
trading."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

import pandas as pd

from data_layer.pacing import HistoricalDataPacingGuard

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class MarketDataProvider(Protocol):
    def get_historical_bars(self, symbol: str, bar_size: str, duration: str) -> pd.DataFrame: ...

    def get_latest_price(self, symbol: str) -> float: ...


def _validate_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{symbol}: bar data missing required columns {missing}")
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    return df


class CSVMarketDataProvider:
    """Reads recorded/replayed OHLCV bars from local CSV files, one file
    per symbol named <symbol>.csv with a 'date' column plus
    open/high/low/close/volume. This is the only provider unit tests and
    backtests use -- it never makes a network call."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def get_historical_bars(self, symbol: str, bar_size: str = "1 day", duration: str | None = None) -> pd.DataFrame:
        path = self.data_dir / f"{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"no recorded bar data for {symbol} at {path}")
        df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        return _validate_bars(df, symbol)

    def get_latest_price(self, symbol: str) -> float:
        df = self.get_historical_bars(symbol)
        return float(df["close"].iloc[-1])


class IBKRMarketDataProvider:
    """Live historical/snapshot data via ib_async, subject to IBKR's
    documented pacing limits. `ib` must already be a connected
    ib_async.IB() instance -- this class does not manage the connection
    lifecycle, execution_layer's connection code does."""

    def __init__(self, ib, pacing_guard: HistoricalDataPacingGuard | None = None):
        self._ib = ib
        self._pacing = pacing_guard or HistoricalDataPacingGuard()

    def get_historical_bars(self, symbol: str, bar_size: str = "1 day", duration: str = "1 Y") -> pd.DataFrame:
        from ib_async import Stock  # deferred: only needed when actually hitting IBKR

        request_key = (symbol, bar_size, duration)
        allowed, reason = self._pacing.check(request_key)
        if not allowed:
            raise RuntimeError(f"refusing historical data request, would violate IBKR pacing limits: {reason}")

        contract = Stock(symbol, "SMART", "USD")
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )
        self._pacing.record(request_key)

        df = pd.DataFrame(
            {
                "date": [b.date for b in bars],
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
            }
        ).set_index("date")
        return _validate_bars(df, symbol)

    def get_latest_price(self, symbol: str) -> float:
        from ib_async import Stock

        contract = Stock(symbol, "SMART", "USD")
        [ticker] = self._ib.reqTickers(contract)
        return float(ticker.marketPrice())
