"""N-day high breakout with volume confirmation.

Rule set (no discretion):
- Enter long when today's close exceeds the highest close of the prior
  `lookback_days` (excluding today), AND today's volume exceeds
  `volume_confirmation_multiple` times the `volume_avg_days` average
  volume (excluding today).
- Stop-loss: `stop_loss_atr_multiple` * ATR(`atr_days`) below entry.
- Exit (handled by signal_layer.exits, applied to open positions): close
  falls back below the breakout level that triggered entry (trend
  failure), or the stop-loss is hit.
"""
from __future__ import annotations

import math

import pandas as pd

from signal_layer.indicators import average_true_range, average_volume, rolling_high
from signal_layer.models import Side, Signal

name = "breakout"


def generate_signals(data: dict[str, pd.DataFrame], params: dict) -> list[Signal]:
    lookback_days = params["lookback_days"]
    volume_confirmation_multiple = params["volume_confirmation_multiple"]
    volume_avg_days = params["volume_avg_days"]
    stop_loss_atr_multiple = params["stop_loss_atr_multiple"]
    atr_days = params["atr_days"]

    signals = []
    for symbol, df in data.items():
        if df.empty:
            continue

        breakout_level = rolling_high(df["close"], lookback_days)
        last_close = float(df["close"].iloc[-1])
        if math.isnan(breakout_level) or last_close <= breakout_level:
            continue

        vol_avg = average_volume(df["volume"], volume_avg_days)
        last_volume = float(df["volume"].iloc[-1])
        if math.isnan(vol_avg) or last_volume < vol_avg * volume_confirmation_multiple:
            continue

        atr = average_true_range(df, atr_days)
        if math.isnan(atr) or atr <= 0:
            continue

        entry_price = last_close
        signals.append(
            Signal(
                symbol=symbol,
                side=Side.BUY,
                strategy_name=name,
                reasoning=(
                    f"close {last_close:.2f} broke {lookback_days}d high {breakout_level:.2f} "
                    f"on volume {last_volume:,.0f} >= {volume_confirmation_multiple}x "
                    f"{volume_avg_days}d avg ({vol_avg:,.0f})"
                ),
                entry_price=entry_price,
                stop_loss_price=entry_price - stop_loss_atr_multiple * atr,
                sector=df.attrs.get("sector", "Unknown"),
                as_of=df.index[-1],
                target_price=None,
            )
        )
    return signals
