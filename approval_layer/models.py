from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ProposalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class StoredProposal:
    id: str
    symbol: str
    side: str
    quantity: float
    estimated_price: float
    notional_usd: float
    sector: str
    strategy_name: str
    reasoning: str
    stop_loss_price: float | None
    target_price: float | None
    status: ProposalStatus
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_note: str | None

    def is_expired(self, now: datetime) -> bool:
        return self.status == ProposalStatus.PENDING and self.expires_at < now
