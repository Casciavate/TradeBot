"""Individual, pure risk-limit checks. Each takes (proposal, portfolio,
config) and returns a LimitResult -- no shared state, no I/O, fully unit
testable. risk_gate.gate.RiskGate composes these; nothing here is aware of
the others."""
from __future__ import annotations

from dataclasses import dataclass

from config.schema import AppConfig
from risk_gate.models import OrderProposal, PortfolioState, Side


@dataclass(frozen=True)
class LimitResult:
    name: str
    passed: bool
    reason: str | None = None


def check_max_order_notional(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    limit = config.risk_limits.max_single_order_notional_usd
    if proposal.notional_usd > limit:
        return LimitResult(
            "max_order_notional",
            False,
            f"order notional ${proposal.notional_usd:,.2f} exceeds absolute ceiling ${limit:,.2f}",
        )
    return LimitResult("max_order_notional", True)


def check_max_position_size(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    if portfolio.equity <= 0:
        return LimitResult("max_position_size", False, "portfolio equity is not positive")

    existing = portfolio.position_exposure_usd(proposal.symbol)
    signed_change = proposal.notional_usd if proposal.side == Side.BUY else -proposal.notional_usd
    resulting_exposure = abs(existing + signed_change)

    limit = config.risk_limits.max_position_pct_of_equity * portfolio.equity
    if resulting_exposure > limit:
        return LimitResult(
            "max_position_size",
            False,
            f"resulting position ${resulting_exposure:,.2f} would exceed "
            f"{config.risk_limits.max_position_pct_of_equity:.1%} of equity (${limit:,.2f})",
        )
    return LimitResult("max_position_size", True)


def check_sector_concentration(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    if portfolio.equity <= 0:
        return LimitResult("sector_concentration", False, "portfolio equity is not positive")

    existing_sector_exposure = portfolio.sector_exposure_usd(proposal.sector)
    signed_change = proposal.notional_usd if proposal.side == Side.BUY else -proposal.notional_usd
    resulting_sector_exposure = abs(existing_sector_exposure + signed_change)

    limit = config.risk_limits.max_sector_concentration_pct * portfolio.equity
    if resulting_sector_exposure > limit:
        return LimitResult(
            "sector_concentration",
            False,
            f"resulting {proposal.sector} exposure ${resulting_sector_exposure:,.2f} would exceed "
            f"{config.risk_limits.max_sector_concentration_pct:.1%} of equity (${limit:,.2f})",
        )
    return LimitResult("sector_concentration", True)


def check_leverage(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    if portfolio.equity <= 0:
        return LimitResult("leverage", False, "portfolio equity is not positive")

    signed_change = proposal.notional_usd if proposal.side == Side.BUY else -proposal.notional_usd
    resulting_gross = max(0.0, portfolio.gross_exposure_usd + signed_change)
    resulting_leverage = resulting_gross / portfolio.equity

    if resulting_leverage > config.risk_limits.max_leverage:
        return LimitResult(
            "leverage",
            False,
            f"resulting leverage {resulting_leverage:.2f}x would exceed cap {config.risk_limits.max_leverage:.2f}x",
        )
    return LimitResult("leverage", True)


def check_no_naked_short(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    """Cash/no-leverage accounts cannot short. A SELL may only reduce or
    flatten an existing long position, never flip it net negative."""
    if proposal.side != Side.SELL:
        return LimitResult("no_naked_short", True)
    if config.account.account_type == "margin_with_leverage":
        return LimitResult("no_naked_short", True)

    existing_position = portfolio.positions.get(proposal.symbol)
    existing_qty = existing_position.quantity if existing_position else 0.0
    resulting_qty = existing_qty - proposal.quantity

    if resulting_qty < -1e-9:
        return LimitResult(
            "no_naked_short",
            False,
            f"SELL {proposal.quantity} of {proposal.symbol} would leave a short position "
            f"({resulting_qty}) on a cash/no-leverage account",
        )
    return LimitResult("no_naked_short", True)


def check_daily_loss_circuit_breaker(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    limit = config.risk_limits.max_daily_loss_pct
    if portfolio.daily_loss_pct >= limit:
        return LimitResult(
            "daily_loss_circuit_breaker",
            False,
            f"daily loss {portfolio.daily_loss_pct:.2%} has breached the {limit:.2%} circuit breaker -- "
            "halted pending human re-enable",
        )
    return LimitResult("daily_loss_circuit_breaker", True)


def check_drawdown_circuit_breaker(proposal: OrderProposal, portfolio: PortfolioState, config: AppConfig) -> LimitResult:
    limit = config.risk_limits.max_drawdown_pct
    if portfolio.drawdown_pct >= limit:
        return LimitResult(
            "drawdown_circuit_breaker",
            False,
            f"drawdown {portfolio.drawdown_pct:.2%} has breached the {limit:.2%} circuit breaker -- "
            "halted pending manual review",
        )
    return LimitResult("drawdown_circuit_breaker", True)


ALL_CHECKS = (
    check_max_order_notional,
    check_max_position_size,
    check_sector_concentration,
    check_leverage,
    check_no_naked_short,
    check_daily_loss_circuit_breaker,
    check_drawdown_circuit_breaker,
)
