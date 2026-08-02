"""Pure universe filtering -- no I/O. Takes whatever instrument metadata the
caller already fetched (from IBKR or a vendor) and applies the liquidity/
asset-class/price rules from config/universe.yaml."""
from __future__ import annotations

from config.schema import UniverseConfig
from data_layer.instruments import Instrument


def filter_universe(instruments: list[Instrument], config: UniverseConfig) -> list[Instrument]:
    result = []
    include_only = set(config.include_symbols_only) if config.include_symbols_only else None
    exclude = set(config.exclude_symbols)

    for inst in instruments:
        if include_only is not None and inst.symbol not in include_only:
            continue
        if inst.symbol in exclude:
            continue
        if inst.asset_class not in config.allowed_asset_classes:
            continue
        if inst.avg_dollar_volume_usd < config.min_avg_dollar_volume_usd:
            continue
        if inst.last_price < config.min_price_usd:
            continue
        if config.max_price_usd is not None and inst.last_price > config.max_price_usd:
            continue
        result.append(inst)

    return result
