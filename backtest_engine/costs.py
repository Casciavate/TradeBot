"""Explicit commission/slippage/spread cost model applied to every
simulated fill. Nothing in the backtest is a "free" trade."""
from __future__ import annotations

from dataclasses import dataclass

from risk_gate.models import Side


@dataclass(frozen=True)
class CostModel:
    commission_per_share: float = 0.005
    commission_minimum: float = 1.0
    slippage_bps: float = 5.0
    spread_bps: float = 2.0

    def commission(self, quantity: float) -> float:
        return max(self.commission_minimum, abs(quantity) * self.commission_per_share)

    def fill_price(self, side: Side, reference_price: float) -> float:
        """Slippage and half the bid/ask spread both work against the
        trader, in the direction implied by the order side."""
        adverse_bps = self.slippage_bps + self.spread_bps / 2
        adjustment = reference_price * (adverse_bps / 10_000)
        if side == Side.BUY:
            return reference_price + adjustment
        return reference_price - adjustment
