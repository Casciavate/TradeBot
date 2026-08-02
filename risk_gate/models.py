"""Data shapes that flow through risk_gate. Pure data -- no I/O, no
dependency on execution_layer or IBKR, so risk_gate can be fully unit
tested without any live connection."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderProposal:
    """A candidate trade coming out of signal_layer, not yet an order.
    risk_gate evaluates these; approval_layer decides whether a human signs
    off; execution_layer is the only thing that can turn one into a real
    IBKR order, and only after that sign-off."""

    proposal_id: str
    symbol: str
    side: Side
    quantity: float
    estimated_price: float
    sector: str
    strategy_name: str
    reasoning: str
    stop_loss_price: float | None = None
    target_price: float | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def notional_usd(self) -> float:
        return abs(self.quantity) * self.estimated_price


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    market_value: float
    sector: str


@dataclass(frozen=True)
class PortfolioState:
    """Snapshot of account state, as reconciled from IBKR (or from the
    backtest engine's simulated ledger). risk_gate treats this as ground
    truth input -- it never fetches or derives it itself."""

    equity: float
    peak_equity: float
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl_today: float = 0.0
    unrealized_pnl_today: float = 0.0
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    @property
    def daily_pnl(self) -> float:
        return self.realized_pnl_today + self.unrealized_pnl_today

    @property
    def daily_loss_pct(self) -> float:
        if self.equity <= 0:
            return 0.0
        loss = max(0.0, -self.daily_pnl)
        return loss / self.equity

    def sector_exposure_usd(self, sector: str) -> float:
        return sum(abs(p.market_value) for p in self.positions.values() if p.sector == sector)

    def position_exposure_usd(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        return abs(pos.market_value) if pos else 0.0

    @property
    def gross_exposure_usd(self) -> float:
        return sum(abs(p.market_value) for p in self.positions.values())


@dataclass(frozen=True)
class RiskDecision:
    proposal_id: str
    approved: bool
    blocked_reasons: tuple[str, ...]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def summary(self) -> str:
        if self.approved:
            return "APPROVED"
        return f"BLOCKED: {'; '.join(self.blocked_reasons)}"
