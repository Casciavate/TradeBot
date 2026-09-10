"""Daily automated summary (build spec section 8): P&L, positions, risk
limit usage, and any circuit breaker trips.

It is built entirely from the append-only audit logs plus one reconciled
portfolio snapshot -- it never queries IBKR itself and never mutates
anything. That means the summary can be regenerated for any past day from
the logs alone, which is the point of keeping them append-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from monitoring.audit_log import AuditLog
from monitoring.risk_usage import LimitUsage, compute_risk_usage

if TYPE_CHECKING:  # pragma: no cover -- import-cycle avoidance
    from config.schema import AppConfig
    from risk_gate.models import PortfolioState


@dataclass(frozen=True)
class PositionLine:
    symbol: str
    quantity: float
    market_value: float
    sector: str


@dataclass(frozen=True)
class DailySummary:
    summary_date: date
    equity: float
    peak_equity: float
    cash: float
    realized_pnl: float
    unrealized_pnl: float
    positions: list[PositionLine]
    risk_usage: list[LimitUsage]
    event_counts: dict[str, int] = field(default_factory=dict)
    circuit_breaker_trips: list[dict] = field(default_factory=list)
    blocked_reasons: dict[str, int] = field(default_factory=dict)
    account_is_placeholder: bool = False

    @property
    def daily_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def daily_pnl_pct(self) -> float:
        if self.equity <= 0:
            return 0.0
        return self.daily_pnl / self.equity

    def render_text(self) -> str:
        lines = [
            f"TradeBot daily summary -- {self.summary_date.isoformat()}",
            "=" * 52,
            "",
            "P&L",
            f"  equity              ${self.equity:,.2f}",
            f"  peak equity         ${self.peak_equity:,.2f}",
            f"  cash                ${self.cash:,.2f}",
            f"  realized today      ${self.realized_pnl:,.2f}",
            f"  unrealized today    ${self.unrealized_pnl:,.2f}",
            f"  net today           ${self.daily_pnl:,.2f} ({self.daily_pnl_pct:.2%})",
            "",
            "Positions",
        ]
        if self.positions:
            for position in self.positions:
                lines.append(
                    f"  {position.symbol:<8} {position.quantity:>10,.2f} "
                    f"${position.market_value:>14,.2f}  {position.sector}"
                )
        else:
            lines.append("  (flat)")

        lines += ["", "Risk limit usage"]
        for item in self.risk_usage:
            marker = "  BREACHED" if item.breached else ""
            lines.append(
                f"  {item.name:<24} {item.format_used():>14} / {item.format_limit():<14} "
                f"({item.utilization:.0%} used, {item.format_headroom()} headroom){marker}"
            )

        lines += ["", "Activity"]
        if self.event_counts:
            for name, count in sorted(self.event_counts.items()):
                lines.append(f"  {name:<28} {count}")
        else:
            lines.append("  (no recorded activity)")

        if self.blocked_reasons:
            lines += ["", "risk_gate blocks by reason"]
            for reason, count in sorted(self.blocked_reasons.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {count:>4}  {reason}")

        lines += ["", "Circuit breakers"]
        if self.circuit_breaker_trips:
            for trip in self.circuit_breaker_trips:
                lines.append(f"  TRIPPED {trip.get('raised_at', '')}: {trip.get('summary', '')}")
            lines.append("  A human must reset before trading resumes: scripts/circuit_breaker_cli.py reset")
        else:
            lines.append("  no trips recorded today")

        if self.account_is_placeholder:
            lines += [
                "",
                "WARNING: config/account.yaml starting_capital_usd is still a placeholder.",
                "Every percentage-based figure above is therefore not meaningful.",
            ]

        return "\n".join(lines)


_COUNTED_EVENTS = {
    "signal_generated": "signals generated",
    "risk_decision": "risk_gate decisions",
    "proposal_created": "proposals queued",
    "proposal_approved": "proposals approved",
    "proposal_rejected": "proposals rejected",
    "proposal_expired": "proposals expired",
    "bulk_proposal_approval": "bulk approvals",
    "order_submitted": "orders submitted",
    "order_state_updated": "order state updates",
    "alert": "alerts raised",
}


def _record_date(record: dict) -> date | None:
    raw = record.get("ts")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).date()
    except (TypeError, ValueError):
        return None


def _read_logs(log_paths: Iterable[str | Path]) -> list[dict]:
    records: list[dict] = []
    for path in log_paths:
        records.extend(AuditLog(path).read_all())
    return records


def build_daily_summary(
    portfolio: "PortfolioState",
    config: "AppConfig",
    log_paths: Iterable[str | Path],
    summary_date: date | None = None,
) -> DailySummary:
    summary_date = summary_date or datetime.now(timezone.utc).date()
    records = [r for r in _read_logs(log_paths) if _record_date(r) == summary_date]

    event_counts: dict[str, int] = {}
    blocked_reasons: dict[str, int] = {}
    circuit_breaker_trips: list[dict] = []

    for record in records:
        event_type = record.get("event_type", "")
        label = _COUNTED_EVENTS.get(event_type)
        if label:
            event_counts[label] = event_counts.get(label, 0) + 1

        if event_type == "risk_decision" and not record.get("approved", True):
            for reason in record.get("blocked_reasons", []):
                key = str(reason).split(":")[0].strip() or str(reason)
                blocked_reasons[key] = blocked_reasons.get(key, 0) + 1

        if event_type == "alert" and record.get("kind") == "circuit_breaker_tripped":
            circuit_breaker_trips.append(record)

    positions = [
        PositionLine(
            symbol=position.symbol,
            quantity=position.quantity,
            market_value=position.market_value,
            sector=position.sector,
        )
        for position in sorted(
            portfolio.positions.values(), key=lambda p: -abs(p.market_value)
        )
    ]

    return DailySummary(
        summary_date=summary_date,
        equity=portfolio.equity,
        peak_equity=portfolio.peak_equity,
        cash=portfolio.cash,
        realized_pnl=portfolio.realized_pnl_today,
        unrealized_pnl=portfolio.unrealized_pnl_today,
        positions=positions,
        risk_usage=compute_risk_usage(portfolio, config),
        event_counts=event_counts,
        circuit_breaker_trips=circuit_breaker_trips,
        blocked_reasons=blocked_reasons,
        account_is_placeholder=config.account.is_placeholder,
    )
