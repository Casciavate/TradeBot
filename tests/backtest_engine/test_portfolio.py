from __future__ import annotations

from datetime import date

from backtest_engine.costs import CostModel
from backtest_engine.portfolio import SimPortfolio
from risk_gate.models import OrderProposal, Side


def make_proposal(symbol="SPY", side=Side.BUY, quantity=10, price=500.0) -> OrderProposal:
    return OrderProposal(
        proposal_id="p1",
        symbol=symbol,
        side=side,
        quantity=quantity,
        estimated_price=price,
        sector="Broad Market",
        strategy_name="momentum",
        reasoning="test",
    )


def test_open_position_deducts_cash_including_costs():
    cost_model = CostModel(commission_per_share=0.0, commission_minimum=1.0, slippage_bps=0.0, spread_bps=0.0)
    portfolio = SimPortfolio(initial_capital=100_000, cost_model=cost_model)
    opened = portfolio.open_position(
        make_proposal(quantity=10, price=500.0), entry_date=date(2024, 1, 1), stop_loss_price=450.0, target_price=None
    )
    assert opened
    assert portfolio.cash == 100_000 - (10 * 500.0 + 1.0)
    assert "SPY" in portfolio.positions


def test_cannot_open_position_exceeding_cash():
    cost_model = CostModel()
    portfolio = SimPortfolio(initial_capital=1_000, cost_model=cost_model)
    opened = portfolio.open_position(
        make_proposal(quantity=100, price=500.0), entry_date=date(2024, 1, 1), stop_loss_price=None, target_price=None
    )
    assert not opened
    assert "SPY" not in portfolio.positions
    assert portfolio.cash == 1_000


def test_close_position_computes_pnl_net_of_costs():
    cost_model = CostModel(commission_per_share=0.0, commission_minimum=1.0, slippage_bps=0.0, spread_bps=0.0)
    portfolio = SimPortfolio(initial_capital=100_000, cost_model=cost_model)
    portfolio.open_position(
        make_proposal(quantity=10, price=500.0), entry_date=date(2024, 1, 1), stop_loss_price=None, target_price=None
    )
    trade = portfolio.close_position("SPY", date(2024, 1, 5), reference_price=550.0, reason="target")
    # entry cost basis = 5000 + 1 = 5001; exit proceeds = 5500 - 1 = 5499
    assert trade.pnl == 5499 - 5001
    assert "SPY" not in portfolio.positions


def test_equity_reflects_open_positions_marked_to_market():
    cost_model = CostModel(commission_per_share=0.0, commission_minimum=0.0, slippage_bps=0.0, spread_bps=0.0)
    portfolio = SimPortfolio(initial_capital=100_000, cost_model=cost_model)
    portfolio.open_position(
        make_proposal(quantity=10, price=500.0), entry_date=date(2024, 1, 1), stop_loss_price=None, target_price=None
    )
    equity = portfolio.equity({"SPY": 600.0})
    assert equity == (100_000 - 5000) + 10 * 600.0


def test_daily_pnl_measures_change_since_last_baseline():
    cost_model = CostModel(commission_per_share=0.0, commission_minimum=0.0, slippage_bps=0.0, spread_bps=0.0)
    portfolio = SimPortfolio(initial_capital=100_000, cost_model=cost_model)
    portfolio.set_daily_baseline({})
    portfolio.open_position(
        make_proposal(quantity=10, price=500.0), entry_date=date(2024, 1, 1), stop_loss_price=None, target_price=None
    )
    pnl = portfolio.daily_pnl({"SPY": 600.0})
    assert pnl == 10 * 600.0 - 10 * 500.0
