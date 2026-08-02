"""The single chokepoint every proposed order must pass through. Strategy
code, backtest_engine, and approval_layer all call RiskGate.evaluate() --
none of them can construct a RiskDecision themselves or skip a check."""
from __future__ import annotations

from datetime import datetime

from config.schema import AppConfig
from monitoring.audit_log import AuditLog
from risk_gate.circuit_breaker import CircuitBreaker
from risk_gate.kill_switch import KillSwitch
from risk_gate.limits import ALL_CHECKS
from risk_gate.models import OrderProposal, PortfolioState, RiskDecision
from risk_gate.rate_limiter import RateLimiter

_CIRCUIT_BREAKER_CHECK_NAMES = {"daily_loss_circuit_breaker", "drawdown_circuit_breaker"}


class RiskGate:
    def __init__(
        self,
        config: AppConfig,
        kill_switch: KillSwitch | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        audit_log: AuditLog | None = None,
        state_dir: str = "state",
    ):
        self.config = config
        self.kill_switch = kill_switch or KillSwitch()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.audit_log = audit_log or AuditLog(f"{state_dir}/risk_gate_audit.log")
        self.rate_limiter = RateLimiter(
            max_per_minute=config.risk_limits.max_orders_per_minute,
            max_per_hour=config.risk_limits.max_orders_per_hour,
        )

    def evaluate(self, proposal: OrderProposal, portfolio: PortfolioState, now: datetime | None = None) -> RiskDecision:
        """`now` defaults to real wall-clock time for live/paper use. The
        backtest engine passes the simulated bar's timestamp instead, so
        order-rate limiting is judged against simulated time -- otherwise
        a multi-year backtest evaluated in milliseconds of wall-clock time
        would trip the per-minute rate limit almost immediately."""
        blocked_reasons: list[str] = []

        if self.kill_switch.is_engaged():
            blocked_reasons.append(f"kill switch engaged: {self.kill_switch.reason()}")
            return self._decide(proposal, blocked_reasons)

        if self.circuit_breaker.is_tripped():
            info = self.circuit_breaker.info() or {}
            blocked_reasons.append(
                f"circuit breaker tripped at {info.get('tripped_at')}: {info.get('reason')} "
                "-- requires human reset"
            )
            return self._decide(proposal, blocked_reasons)

        rate_ok, rate_reason = self.rate_limiter.hit(now)
        if not rate_ok:
            blocked_reasons.append(rate_reason or "rate limit exceeded")
            return self._decide(proposal, blocked_reasons)

        tripped_reason = None
        for check in ALL_CHECKS:
            result = check(proposal, portfolio, self.config)
            if not result.passed:
                blocked_reasons.append(f"{result.name}: {result.reason}")
                if result.name in _CIRCUIT_BREAKER_CHECK_NAMES:
                    tripped_reason = result.reason

        if tripped_reason:
            self.circuit_breaker.trip(tripped_reason)

        return self._decide(proposal, blocked_reasons)

    def _decide(self, proposal: OrderProposal, blocked_reasons: list[str]) -> RiskDecision:
        decision = RiskDecision(
            proposal_id=proposal.proposal_id,
            approved=not blocked_reasons,
            blocked_reasons=tuple(blocked_reasons),
        )
        self.audit_log.write(
            "risk_decision",
            {
                "proposal_id": proposal.proposal_id,
                "symbol": proposal.symbol,
                "side": proposal.side.value,
                "quantity": proposal.quantity,
                "notional_usd": proposal.notional_usd,
                "strategy_name": proposal.strategy_name,
                "approved": decision.approved,
                "blocked_reasons": list(decision.blocked_reasons),
            },
        )
        return decision
