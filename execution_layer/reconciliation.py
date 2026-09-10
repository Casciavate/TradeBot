"""Position reconciliation against IBKR's own reported positions. Must run
every cycle -- local order-state bookkeeping is never trusted alone.

A discrepancy raises a CRITICAL alert (section 8) and is never silently
patched over: if local state and IBKR disagree about what is held, the
correct response is a human looking at it, not code picking a winner.
"""
from __future__ import annotations

from dataclasses import dataclass

from monitoring.alerts import AlertKind, AlertRouter, AlertSeverity

_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ReconciliationDiscrepancy:
    symbol: str
    local_quantity: float
    ibkr_quantity: float

    @property
    def difference(self) -> float:
        return self.local_quantity - self.ibkr_quantity

    def describe(self) -> str:
        return (
            f"{self.symbol}: local {self.local_quantity:g} vs IBKR {self.ibkr_quantity:g} "
            f"(difference {self.difference:+g})"
        )


def reconcile_positions(
    local_positions: dict[str, float],
    ibkr_positions: dict[str, float],
    alert_router: AlertRouter | None = None,
) -> list[ReconciliationDiscrepancy]:
    discrepancies = []
    for symbol in sorted(set(local_positions) | set(ibkr_positions)):
        local_qty = local_positions.get(symbol, 0.0)
        ibkr_qty = ibkr_positions.get(symbol, 0.0)
        if abs(local_qty - ibkr_qty) > _TOLERANCE:
            discrepancies.append(ReconciliationDiscrepancy(symbol, local_qty, ibkr_qty))

    if discrepancies and alert_router is not None:
        alert_router.alert(
            AlertKind.POSITION_RECONCILIATION_MISMATCH,
            AlertSeverity.CRITICAL,
            f"Position reconciliation mismatch on {len(discrepancies)} symbol(s) -- "
            "IBKR is ground truth, local state is not",
            {
                "symbols": [d.symbol for d in discrepancies],
                "detail": [d.describe() for d in discrepancies],
            },
            dedup_key=",".join(d.symbol for d in discrepancies),
        )

    return discrepancies
