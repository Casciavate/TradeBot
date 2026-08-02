from __future__ import annotations

from execution_layer.reconciliation import reconcile_positions


def test_no_discrepancies_when_positions_match():
    local = {"SPY": 10.0, "QQQ": 5.0}
    ibkr = {"SPY": 10.0, "QQQ": 5.0}
    assert reconcile_positions(local, ibkr) == []


def test_detects_quantity_mismatch():
    local = {"SPY": 10.0}
    ibkr = {"SPY": 8.0}
    [discrepancy] = reconcile_positions(local, ibkr)
    assert discrepancy.symbol == "SPY"
    assert discrepancy.difference == 2.0


def test_detects_position_missing_locally():
    local = {}
    ibkr = {"SPY": 10.0}
    [discrepancy] = reconcile_positions(local, ibkr)
    assert discrepancy.local_quantity == 0.0
    assert discrepancy.ibkr_quantity == 10.0


def test_detects_position_missing_at_broker():
    local = {"SPY": 10.0}
    ibkr = {}
    [discrepancy] = reconcile_positions(local, ibkr)
    assert discrepancy.ibkr_quantity == 0.0


def test_tiny_floating_point_differences_are_not_flagged():
    local = {"SPY": 10.0000001}
    ibkr = {"SPY": 10.0}
    assert reconcile_positions(local, ibkr) == []
