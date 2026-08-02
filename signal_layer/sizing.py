"""Turns a directional Signal into a candidate risk_gate.OrderProposal.
This is the one deliberate seam where signal_layer touches account state
(equity) -- the strategies themselves stay pure. The size computed here is
only ever a proposal: risk_gate re-derives and re-checks every limit
independently and can reject or the proposal regardless of this math."""
from __future__ import annotations

import math
import uuid

from risk_gate.models import OrderProposal, Side as RiskSide
from signal_layer.models import Signal


def size_signal(
    signal: Signal,
    equity: float,
    max_position_pct_of_equity: float,
    proposal_id: str | None = None,
) -> OrderProposal | None:
    if signal.entry_price <= 0 or equity <= 0:
        return None

    max_notional = equity * max_position_pct_of_equity
    quantity = math.floor(max_notional / signal.entry_price)
    if quantity <= 0:
        return None

    return OrderProposal(
        proposal_id=proposal_id or str(uuid.uuid4()),
        symbol=signal.symbol,
        side=RiskSide(signal.side.value),
        quantity=quantity,
        estimated_price=signal.entry_price,
        sector=signal.sector,
        strategy_name=signal.strategy_name,
        reasoning=signal.reasoning,
        stop_loss_price=signal.stop_loss_price,
        target_price=signal.target_price,
    )
