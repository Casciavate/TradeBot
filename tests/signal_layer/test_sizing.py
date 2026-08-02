from __future__ import annotations

from datetime import datetime, timezone

from risk_gate.models import Side as RiskSide
from signal_layer.models import Side, Signal
from signal_layer.sizing import size_signal


def make_signal(entry_price: float = 500.0, side: Side = Side.BUY) -> Signal:
    return Signal(
        symbol="SPY",
        side=side,
        strategy_name="momentum",
        reasoning="test",
        entry_price=entry_price,
        stop_loss_price=entry_price * 0.9,
        sector="Broad Market",
        as_of=datetime.now(timezone.utc),
    )


def test_sizes_within_position_cap():
    proposal = size_signal(make_signal(500.0), equity=100_000, max_position_pct_of_equity=0.08)
    assert proposal is not None
    assert proposal.quantity == 16  # floor(8000 / 500)
    assert proposal.side == RiskSide.BUY
    assert proposal.symbol == "SPY"


def test_zero_equity_returns_none():
    proposal = size_signal(make_signal(500.0), equity=0, max_position_pct_of_equity=0.08)
    assert proposal is None


def test_price_too_high_for_any_shares_returns_none():
    proposal = size_signal(make_signal(1_000_000.0), equity=100_000, max_position_pct_of_equity=0.08)
    assert proposal is None


def test_carries_through_stop_loss_and_reasoning():
    signal = make_signal(500.0)
    proposal = size_signal(signal, equity=100_000, max_position_pct_of_equity=0.08, proposal_id="fixed-id")
    assert proposal.proposal_id == "fixed-id"
    assert proposal.stop_loss_price == signal.stop_loss_price
    assert proposal.reasoning == signal.reasoning
