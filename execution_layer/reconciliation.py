"""Position reconciliation against IBKR's own reported positions. Must run
every cycle -- local order-state bookkeeping is never trusted alone. Any
discrepancy here should raise a monitoring alert (section 8), not be
silently patched over."""
from __future__ import annotations

from dataclasses import dataclass

_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ReconciliationDiscrepancy:
    symbol: str
    local_quantity: float
    ibkr_quantity: float

    @property
    def difference(self) -> float:
        return self.local_quantity - self.ibkr_quantity


def reconcile_positions(local_positions: dict[str, float], ibkr_positions: dict[str, float]) -> list[ReconciliationDiscrepancy]:
    discrepancies = []
    for symbol in set(local_positions) | set(ibkr_positions):
        local_qty = local_positions.get(symbol, 0.0)
        ibkr_qty = ibkr_positions.get(symbol, 0.0)
        if abs(local_qty - ibkr_qty) > _TOLERANCE:
            discrepancies.append(ReconciliationDiscrepancy(symbol, local_qty, ibkr_qty))
    return discrepancies
