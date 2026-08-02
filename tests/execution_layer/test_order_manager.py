from __future__ import annotations

from types import SimpleNamespace

import pytest

from execution_layer.order_manager import OrderManager, OrderState
from monitoring.audit_log import AuditLog
from risk_gate.models import OrderProposal, Side


def make_proposal(side=Side.BUY, quantity=10, symbol="SPY", proposal_id="p1") -> OrderProposal:
    return OrderProposal(
        proposal_id=proposal_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        estimated_price=500.0,
        sector="Broad Market",
        strategy_name="momentum",
        reasoning="approved by human",
    )


class FakeIB:
    """Minimal stand-in for a connected ib_async.IB(). No network, no
    event loop -- just enough surface for OrderManager to exercise."""

    def __init__(self):
        self.placed_orders = []
        self._next_id = 1000
        self.fill_immediately = True

    def placeOrder(self, contract, order):
        order_id = self._next_id
        self._next_id += 1
        order.orderId = order_id
        self.placed_orders.append((contract, order))
        filled = order.totalQuantity if self.fill_immediately else 0.0
        status = "Filled" if self.fill_immediately else "Submitted"
        return SimpleNamespace(
            order=SimpleNamespace(orderId=order_id),
            orderStatus=SimpleNamespace(status=status, filled=filled, avgFillPrice=order.lmtPrice if self.fill_immediately else 0.0),
            contract=contract,
        )

    def positions(self, account: str = ""):
        return []

    def isConnected(self) -> bool:
        return True


@pytest.fixture
def audit_log(tmp_path) -> AuditLog:
    return AuditLog(tmp_path / "execution_audit.log")


def test_buy_limit_price_is_above_reference_within_slippage_tolerance(audit_log):
    ib = FakeIB()
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    price = manager.limit_price_for(Side.BUY, 500.0)
    assert price == pytest.approx(500.5, abs=0.01)


def test_sell_limit_price_is_below_reference_within_slippage_tolerance(audit_log):
    ib = FakeIB()
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    price = manager.limit_price_for(Side.SELL, 500.0)
    assert price == pytest.approx(499.5, abs=0.01)


def test_submit_order_places_a_limit_order_not_a_market_order(audit_log):
    ib = FakeIB()
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    manager.submit_order(make_proposal(), reference_price=500.0)

    [(contract, order)] = ib.placed_orders
    assert order.orderType == "LMT"
    assert order.action == "BUY"
    assert order.totalQuantity == 10
    assert contract.symbol == "SPY"


def test_submit_order_tracks_filled_state(audit_log):
    ib = FakeIB()
    ib.fill_immediately = True
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    record = manager.submit_order(make_proposal(quantity=10), reference_price=500.0)
    assert record.state == OrderState.FILLED
    assert record.proposal_id == "p1"


def test_submit_order_tracks_submitted_state_when_unfilled(audit_log):
    ib = FakeIB()
    ib.fill_immediately = False
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    record = manager.submit_order(make_proposal(quantity=10), reference_price=500.0)
    assert record.state == OrderState.SUBMITTED


def test_refresh_order_state_detects_partial_fill(audit_log):
    ib = FakeIB()
    ib.fill_immediately = False
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    record = manager.submit_order(make_proposal(quantity=10), reference_price=500.0)

    updated = manager.refresh_order_state(record.ibkr_order_id, ib_status="Submitted", filled=4, avg_fill_price=500.25)
    assert updated.state == OrderState.PARTIALLY_FILLED
    assert updated.filled_quantity == 4


def test_refresh_order_state_detects_cancellation(audit_log):
    ib = FakeIB()
    ib.fill_immediately = False
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    record = manager.submit_order(make_proposal(quantity=10), reference_price=500.0)

    updated = manager.refresh_order_state(record.ibkr_order_id, ib_status="Cancelled", filled=0, avg_fill_price=None)
    assert updated.state == OrderState.CANCELLED


def test_every_submission_is_audit_logged(audit_log):
    ib = FakeIB()
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    manager.submit_order(make_proposal(), reference_price=500.0)
    records = audit_log.read_all()
    assert records[0]["event_type"] == "order_submitted"
    assert records[0]["symbol"] == "SPY"


def test_local_positions_reflects_filled_quantity_signed_by_side(audit_log):
    ib = FakeIB()
    ib.fill_immediately = True
    manager = OrderManager(ib, max_slippage_bps=10.0, audit_log=audit_log)
    manager.submit_order(make_proposal(side=Side.BUY, quantity=10, symbol="SPY", proposal_id="p1"), reference_price=500.0)
    manager.submit_order(make_proposal(side=Side.SELL, quantity=4, symbol="SPY", proposal_id="p2"), reference_price=500.0)
    assert manager.local_positions()["SPY"] == 6
