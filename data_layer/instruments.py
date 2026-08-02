from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str  # "ETF" for now -- see config/universe.yaml
    sector: str
    avg_dollar_volume_usd: float
    last_price: float
