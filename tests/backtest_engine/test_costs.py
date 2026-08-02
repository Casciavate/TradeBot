from __future__ import annotations

from backtest_engine.costs import CostModel
from risk_gate.models import Side


def test_commission_uses_minimum_for_small_orders():
    model = CostModel(commission_per_share=0.005, commission_minimum=1.0)
    assert model.commission(quantity=10) == 1.0  # 10 * 0.005 = 0.05 < minimum


def test_commission_scales_above_minimum():
    model = CostModel(commission_per_share=0.005, commission_minimum=1.0)
    assert model.commission(quantity=1000) == 5.0


def test_buy_fill_price_is_worse_than_reference():
    model = CostModel(slippage_bps=5.0, spread_bps=2.0)
    fill = model.fill_price(Side.BUY, 100.0)
    assert fill > 100.0


def test_sell_fill_price_is_worse_than_reference():
    model = CostModel(slippage_bps=5.0, spread_bps=2.0)
    fill = model.fill_price(Side.SELL, 100.0)
    assert fill < 100.0


def test_zero_cost_model_leaves_price_unchanged():
    model = CostModel(slippage_bps=0.0, spread_bps=0.0)
    assert model.fill_price(Side.BUY, 100.0) == 100.0
