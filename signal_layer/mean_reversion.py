"""Mean reversion off a rolling z-score.

Rule set (no discretion):
- Compute the z-score of the last close against the trailing
  `lookback_days` mean/std.
- Enter long when z-score <= `entry_zscore` (price is statistically far
  below its recent mean).
- Stop-loss: fixed `stop_loss_pct` below entry.
- Exit (handled by signal_layer.exits, applied to open positions):
  z-score reverts to >= `exit_zscore`, or `max_hold_days` elapses,
  whichever comes first.
"""
from __future__ import annotations

import math

import pandas as pd

from signal_layer.indicators import rolling_zscore
from signal_layer.models import Side, Signal

name = "mean_reversion"


def generate_signals(data: dict[str, pd.DataFrame], params: dict) -> list[Signal]:
    lookback_days = params["lookback_days"]
    entry_zscore = params["entry_zscore"]
    stop_loss_pct = params["stop_loss_pct"]

    signals = []
    for symbol, df in data.items():
        if df.empty:
            continue
        z = rolling_zscore(df["close"], lookback_days)
        if math.isnan(z) or z > entry_zscore:
            continue

        entry_price = float(df["close"].iloc[-1])
        signals.append(
            Signal(
                symbol=symbol,
                side=Side.BUY,
                strategy_name=name,
                reasoning=(
                    f"{lookback_days}d z-score {z:.2f} <= entry threshold {entry_zscore:.2f}"
                ),
                entry_price=entry_price,
                stop_loss_price=entry_price * (1 - stop_loss_pct),
                sector=df.attrs.get("sector", "Unknown"),
                as_of=df.index[-1],
            )
        )
    return signals
