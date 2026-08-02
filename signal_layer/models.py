"""Signal shapes. Deliberately independent of risk_gate/execution_layer --
signal_layer only ever imports pandas/numpy and its own modules, so it can
be unit tested with zero I/O and zero knowledge of account state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Side
    strategy_name: str
    reasoning: str
    entry_price: float
    stop_loss_price: float
    sector: str
    target_price: float | None = None
    as_of: datetime | None = None
