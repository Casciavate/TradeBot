"""Risk-limit headroom: how much of each configured limit is currently
consumed (build spec section 8's "risk limit headroom").

This is a read-only view for humans and the daily summary. It deliberately
does NOT enforce anything -- enforcement lives in risk_gate/limits.py and
nothing here is in the order path. The two read the same config values, so
if a number here looks wrong, the config is wrong, not this display.

Typing-only imports keep monitoring free of any runtime dependency on
risk_gate or config, so both can import monitoring without a cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- import-cycle avoidance, not logic
    from config.schema import AppConfig
    from risk_gate.models import PortfolioState


@dataclass(frozen=True)
class LimitUsage:
    """One risk limit's current consumption. `used` and `limit` share
    `unit`, so utilization is always a clean ratio."""

    name: str
    used: float
    limit: float
    unit: str
    detail: str = ""

    @property
    def utilization(self) -> float:
        """Fraction of the limit consumed. Capped at 0 below, uncapped
        above 1.0 so a breach is visible as e.g. 1.4 rather than clipped."""
        if self.limit <= 0:
            return 0.0
        return max(0.0, self.used / self.limit)

    @property
    def headroom(self) -> float:
        return max(0.0, self.limit - self.used)

    @property
    def breached(self) -> bool:
        return self.used >= self.limit

    def format_used(self) -> str:
        return _format_value(self.used, self.unit)

    def format_limit(self) -> str:
        return _format_value(self.limit, self.unit)

    def format_headroom(self) -> str:
        return _format_value(self.headroom, self.unit)


def _format_value(value: float, unit: str) -> str:
    if unit == "usd":
        return f"${value:,.2f}"
    if unit == "pct":
        return f"{value:.2%}"
    if unit == "x":
        return f"{value:.2f}x"
    return f"{value:,.0f}"


def compute_risk_usage(portfolio: "PortfolioState", config: "AppConfig") -> list[LimitUsage]:
    """Current consumption of every equity-relative risk limit.

    Order-rate limits are excluded: they are windowed counters owned by
    risk_gate.rate_limiter, not a property of a portfolio snapshot.
    """
    limits = config.risk_limits
    equity = portfolio.equity
    usage: list[LimitUsage] = []

    largest_symbol, largest_value = _largest_position(portfolio)
    usage.append(
        LimitUsage(
            name="largest position",
            used=largest_value,
            limit=limits.max_position_pct_of_equity * equity,
            unit="usd",
            detail=largest_symbol or "no open positions",
        )
    )

    largest_sector, largest_sector_value = _largest_sector(portfolio)
    usage.append(
        LimitUsage(
            name="largest sector exposure",
            used=largest_sector_value,
            limit=limits.max_sector_concentration_pct * equity,
            unit="usd",
            detail=largest_sector or "no open positions",
        )
    )

    usage.append(
        LimitUsage(
            name="daily loss",
            used=portfolio.daily_loss_pct,
            limit=limits.max_daily_loss_pct,
            unit="pct",
            detail="circuit breaker -- halts new orders until a human re-enables",
        )
    )

    usage.append(
        LimitUsage(
            name="drawdown from peak",
            used=portfolio.drawdown_pct,
            limit=limits.max_drawdown_pct,
            unit="pct",
            detail="circuit breaker -- halts trading pending manual review",
        )
    )

    usage.append(
        LimitUsage(
            name="gross leverage",
            used=(portfolio.gross_exposure_usd / equity) if equity > 0 else 0.0,
            limit=limits.max_leverage,
            unit="x",
            detail=f"account_type={config.account.account_type}",
        )
    )

    return usage


def _largest_position(portfolio: "PortfolioState") -> tuple[str | None, float]:
    if not portfolio.positions:
        return None, 0.0
    symbol, position = max(
        portfolio.positions.items(), key=lambda item: abs(item[1].market_value)
    )
    return symbol, abs(position.market_value)


def _largest_sector(portfolio: "PortfolioState") -> tuple[str | None, float]:
    if not portfolio.positions:
        return None, 0.0
    totals: dict[str, float] = {}
    for position in portfolio.positions.values():
        totals[position.sector] = totals.get(position.sector, 0.0) + abs(position.market_value)
    sector, value = max(totals.items(), key=lambda item: item[1])
    return sector, value


def breached_limits(usage: list[LimitUsage]) -> list[LimitUsage]:
    return [item for item in usage if item.breached]
