"""The only piece of code in this system that can submit an order to
IBKR. It is only ever invoked by approval_layer's on_approved callback,
after a recorded human approval -- signal_layer and risk_gate have no
import path to this class or to a connected broker client.

Orders are always limit orders, priced within `max_slippage_bps` of the
reference price passed in -- never naive market orders."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from execution_layer.broker_client import BrokerClient
from monitoring.audit_log import AuditLog
from risk_gate.models import OrderProposal, Side


class OrderState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


_IB_CANCELLED_STATUSES = {"Cancelled", "ApiCancelled"}
_IB_REJECTED_STATUSES = {"Inactive"}


@dataclass
class OrderRecord:
    ibkr_order_id: int
    proposal_id: str
    symbol: str
    side: Side
    quantity: float
    limit_price: float
    state: OrderState
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _derive_state(quantity: float, filled: float, ib_status: str) -> OrderState:
    """Filled quantity is the ground truth for fill state; the IB status
    string only matters for cancelled/rejected orders that never filled."""
    if filled >= quantity and quantity > 0:
        return OrderState.FILLED
    if filled > 0:
        return OrderState.PARTIALLY_FILLED
    if ib_status in _IB_CANCELLED_STATUSES:
        return OrderState.CANCELLED
    if ib_status in _IB_REJECTED_STATUSES:
        return OrderState.REJECTED
    return OrderState.SUBMITTED


class OrderManager:
    def __init__(self, ib: BrokerClient, max_slippage_bps: float, audit_log: AuditLog | None = None, state_dir: str = "state"):
        self._ib = ib
        self.max_slippage_bps = max_slippage_bps
        self.audit_log = audit_log or AuditLog(f"{state_dir}/execution_audit.log")
        self.orders: dict[int, OrderRecord] = {}

    def limit_price_for(self, side: Side, reference_price: float) -> float:
        adjustment = reference_price * (self.max_slippage_bps / 10_000)
        if side == Side.BUY:
            return round(reference_price + adjustment, 2)
        return round(reference_price - adjustment, 2)

    def submit_order(self, proposal: OrderProposal, reference_price: float) -> OrderRecord:
        from ib_async import LimitOrder, Stock

        limit_price = self.limit_price_for(proposal.side, reference_price)
        contract = Stock(proposal.symbol, "SMART", "USD")
        order = LimitOrder(proposal.side.value, proposal.quantity, limit_price)

        trade = self._ib.placeOrder(contract, order)
        order_id = trade.order.orderId
        filled = trade.orderStatus.filled
        avg_fill_price = trade.orderStatus.avgFillPrice or None

        record = OrderRecord(
            ibkr_order_id=order_id,
            proposal_id=proposal.proposal_id,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            limit_price=limit_price,
            state=_derive_state(proposal.quantity, filled, trade.orderStatus.status),
            filled_quantity=filled,
            avg_fill_price=avg_fill_price,
        )
        self.orders[order_id] = record
        self.audit_log.write(
            "order_submitted",
            {
                "proposal_id": proposal.proposal_id,
                "order_id": order_id,
                "symbol": proposal.symbol,
                "side": proposal.side.value,
                "quantity": proposal.quantity,
                "limit_price": limit_price,
                "reference_price": reference_price,
            },
        )
        return record

    def refresh_order_state(self, order_id: int, ib_status: str, filled: float, avg_fill_price: float | None) -> OrderRecord:
        record = self.orders[order_id]
        record.state = _derive_state(record.quantity, filled, ib_status)
        record.filled_quantity = filled
        record.avg_fill_price = avg_fill_price
        record.updated_at = datetime.now(timezone.utc)
        self.audit_log.write(
            "order_state_updated",
            {
                "order_id": order_id,
                "symbol": record.symbol,
                "state": record.state.value,
                "filled_quantity": filled,
                "avg_fill_price": avg_fill_price,
            },
        )
        return record

    def local_positions(self) -> dict[str, float]:
        """Net quantity per symbol implied by locally tracked orders --
        this is only ever used as one side of a reconciliation check
        (execution_layer.reconciliation), never trusted on its own."""
        totals: dict[str, float] = {}
        for record in self.orders.values():
            signed = record.filled_quantity if record.side == Side.BUY else -record.filled_quantity
            totals[record.symbol] = totals.get(record.symbol, 0.0) + signed
        return totals
