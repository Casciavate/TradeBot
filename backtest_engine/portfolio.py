"""Simulated single-account portfolio ledger for backtest_engine. Every
fill goes through CostModel; nothing is frictionless."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type

from backtest_engine.costs import CostModel
from risk_gate.models import OrderProposal, Position, Side


@dataclass
class OpenPosition:
    symbol: str
    strategy_name: str
    side: Side
    quantity: float
    entry_price: float
    entry_date: date_type
    entry_cost_basis: float
    stop_loss_price: float | None
    target_price: float | None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Trade:
    symbol: str
    strategy_name: str
    side: Side
    quantity: float
    entry_date: date_type
    entry_price: float
    exit_date: date_type
    exit_price: float
    pnl: float
    exit_reason: str


class SimPortfolio:
    def __init__(self, initial_capital: float, cost_model: CostModel):
        self.cash = initial_capital
        self.peak_equity = initial_capital
        self.positions: dict[str, OpenPosition] = {}
        self.closed_trades: list[Trade] = []
        self.cost_model = cost_model
        self._equity_at_start_of_day: float = initial_capital

    def set_daily_baseline(self, marks: dict[str, float]) -> None:
        """Call once after each simulated day's trades are done, to
        establish the baseline the *next* day's daily_pnl is measured
        against. The constructor sets the initial baseline to
        initial_capital for day one."""
        self._equity_at_start_of_day = self.equity(marks)

    def equity(self, marks: dict[str, float]) -> float:
        position_value = sum(
            pos.quantity * marks.get(pos.symbol, pos.entry_price) for pos in self.positions.values()
        )
        return self.cash + position_value

    def daily_pnl(self, marks: dict[str, float]) -> float:
        return self.equity(marks) - self._equity_at_start_of_day

    def sector_of(self, symbol: str) -> str | None:
        pos = self.positions.get(symbol)
        return pos.extra.get("sector") if pos else None

    def to_risk_gate_state(self, marks: dict[str, float], sectors: dict[str, str]):
        from risk_gate.models import PortfolioState

        equity_now = self.equity(marks)
        self.peak_equity = max(self.peak_equity, equity_now)
        positions = {
            symbol: Position(
                symbol=symbol,
                quantity=pos.quantity,
                market_value=pos.quantity * marks.get(symbol, pos.entry_price),
                sector=sectors.get(symbol, "Unknown"),
            )
            for symbol, pos in self.positions.items()
        }
        return PortfolioState(
            equity=equity_now,
            peak_equity=self.peak_equity,
            cash=self.cash,
            positions=positions,
            realized_pnl_today=0.0,
            unrealized_pnl_today=self.daily_pnl(marks),
        )

    def can_open(self, proposal: OrderProposal) -> bool:
        fill_price = self.cost_model.fill_price(proposal.side, proposal.estimated_price)
        commission = self.cost_model.commission(proposal.quantity)
        return self.cash >= fill_price * proposal.quantity + commission

    def open_position(
        self,
        proposal: OrderProposal,
        entry_date: date_type,
        stop_loss_price: float | None,
        target_price: float | None,
        extra: dict | None = None,
    ) -> bool:
        fill_price = self.cost_model.fill_price(proposal.side, proposal.estimated_price)
        commission = self.cost_model.commission(proposal.quantity)
        cost_basis = fill_price * proposal.quantity + commission
        if cost_basis > self.cash:
            return False

        self.cash -= cost_basis
        self.positions[proposal.symbol] = OpenPosition(
            symbol=proposal.symbol,
            strategy_name=proposal.strategy_name,
            side=proposal.side,
            quantity=proposal.quantity,
            entry_price=fill_price,
            entry_date=entry_date,
            entry_cost_basis=cost_basis,
            stop_loss_price=stop_loss_price,
            target_price=target_price,
            extra=extra or {},
        )
        return True

    def close_position(self, symbol: str, exit_date: date_type, reference_price: float, reason: str) -> Trade:
        pos = self.positions.pop(symbol)
        exit_side = Side.SELL if pos.side == Side.BUY else Side.BUY
        fill_price = self.cost_model.fill_price(exit_side, reference_price)
        commission = self.cost_model.commission(pos.quantity)
        proceeds = fill_price * pos.quantity - commission
        self.cash += proceeds

        pnl = proceeds - pos.entry_cost_basis
        trade = Trade(
            symbol=symbol,
            strategy_name=pos.strategy_name,
            side=pos.side,
            quantity=pos.quantity,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            exit_date=exit_date,
            exit_price=fill_price,
            pnl=pnl,
            exit_reason=reason,
        )
        self.closed_trades.append(trade)
        return trade
