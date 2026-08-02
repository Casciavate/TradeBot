from __future__ import annotations

from typing import Protocol

import pandas as pd

from signal_layer.models import Signal


class Strategy(Protocol):
    """(historical_data) -> signals. No I/O, no side effects, no
    knowledge of the account or of other strategies. `data` maps symbol ->
    an OHLCV DataFrame (see data_layer.market_data), sorted by date
    ascending, with the most recent bar last. Each DataFrame carries its
    sector in `df.attrs["sector"]` (set by whoever assembles the data
    dict); strategies read it from there rather than taking a separate
    metadata argument."""

    name: str

    def generate_signals(self, data: dict[str, pd.DataFrame], params: dict) -> list[Signal]: ...
