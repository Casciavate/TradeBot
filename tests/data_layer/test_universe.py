from __future__ import annotations

from config.schema import UniverseConfig
from data_layer.instruments import Instrument
from data_layer.universe import filter_universe


def make_universe_config(**overrides) -> UniverseConfig:
    defaults = dict(
        allowed_asset_classes=["ETF"],
        min_avg_dollar_volume_usd=10_000_000,
        min_price_usd=5.0,
        max_price_usd=None,
        exclude_symbols=[],
        include_symbols_only=None,
    )
    defaults.update(overrides)
    return UniverseConfig(**defaults)


SPY = Instrument("SPY", "ETF", "Broad Market", avg_dollar_volume_usd=5e10, last_price=500.0)
PENNY = Instrument("PENY", "ETF", "Small Cap", avg_dollar_volume_usd=1e5, last_price=1.0)
STOCK = Instrument("AAPL", "EQUITY", "Tech", avg_dollar_volume_usd=1e10, last_price=200.0)
THIN_ETF = Instrument("THIN", "ETF", "Niche", avg_dollar_volume_usd=1e6, last_price=20.0)


def test_filters_out_illiquid_instruments():
    result = filter_universe([SPY, THIN_ETF], make_universe_config())
    assert result == [SPY]


def test_filters_out_disallowed_asset_class():
    result = filter_universe([SPY, STOCK], make_universe_config())
    assert result == [SPY]


def test_filters_out_below_min_price():
    result = filter_universe([SPY, PENNY], make_universe_config())
    assert result == [SPY]


def test_respects_exclude_list():
    result = filter_universe([SPY], make_universe_config(exclude_symbols=["SPY"]))
    assert result == []


def test_include_only_restricts_universe():
    result = filter_universe([SPY, THIN_ETF], make_universe_config(include_symbols_only=["THIN"], min_avg_dollar_volume_usd=1e5))
    assert result == [THIN_ETF]


def test_max_price_filter():
    result = filter_universe([SPY], make_universe_config(max_price_usd=100.0))
    assert result == []
