"""Momentum / relative-strength ranking.

Rule set (no discretion):
- Rank the universe by total return over `lookback_days`, ending
  `skip_recent_days` before the last bar (classic 12-1 style momentum,
  skipping the most recent month to avoid short-term reversal).
- Enter the top `top_n` ranked symbols with positive momentum, equal
  weight, at the last close.
- Stop-loss: fixed `stop_loss_pct` below entry.
- Exit: a held symbol is exited at the next `rebalance_every_days` if it
  is no longer in the top `top_n` when this function is re-run -- there is
  no separate exit signal to compute, since re-running generate_signals at
  each rebalance date already reports the current target list.
"""
from __future__ import annotations

import math

import pandas as pd

from signal_layer.indicators import total_return
from signal_layer.models import Side, Signal

name = "momentum"


def generate_signals(data: dict[str, pd.DataFrame], params: dict) -> list[Signal]:
    lookback_days = params["lookback_days"]
    skip_recent_days = params.get("skip_recent_days", 0)
    top_n = params["top_n"]
    stop_loss_pct = params["stop_loss_pct"]

    scored = []
    for symbol, df in data.items():
        if df.empty:
            continue
        ret = total_return(df["close"], lookback_days, skip_recent_days)
        if math.isnan(ret):
            continue
        scored.append((symbol, ret, df))

    scored.sort(key=lambda item: item[1], reverse=True)

    signals = []
    for symbol, ret, df in scored[:top_n]:
        if ret <= 0:
            continue
        entry_price = float(df["close"].iloc[-1])
        signals.append(
            Signal(
                symbol=symbol,
                side=Side.BUY,
                strategy_name=name,
                reasoning=(
                    f"{lookback_days}d return (skipping most recent {skip_recent_days}d) "
                    f"of {ret:.2%} ranks in top {top_n} of {len(scored)} scored symbols"
                ),
                entry_price=entry_price,
                stop_loss_price=entry_price * (1 - stop_loss_pct),
                sector=df.attrs.get("sector", "Unknown"),
                as_of=df.index[-1],
            )
        )
    return signals
