"""SQLite-backed proposal store. Every proposal that clears risk_gate
lands here as PENDING; it only ever becomes APPROVED, REJECTED, or EXPIRED
through the methods below, each of which writes a timestamped audit
record. There is no method that turns a proposal into an order -- that
happens one layer up, in the dashboard's on_approved callback, which is
wired to execution_layer only after a human approval is recorded here."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from approval_layer.models import ProposalStatus, StoredProposal
from monitoring.audit_log import AuditLog
from risk_gate.models import OrderProposal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    estimated_price REAL NOT NULL,
    notional_usd REAL NOT NULL,
    sector TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    stop_loss_price REAL,
    target_price REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    decision_note TEXT
);
"""


class ProposalAlreadyDecidedError(Exception):
    pass


class ProposalExpiredError(Exception):
    pass


class BulkApprovalDisabledError(Exception):
    pass


class ProposalStore:
    def __init__(self, db_path: str | Path, audit_log: AuditLog | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_log = audit_log or AuditLog(self.db_path.parent / "approval_audit.log")
        with closing(self._connect()) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, proposal: OrderProposal, expiry_minutes: int, now: datetime | None = None) -> StoredProposal:
        now = now or datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=expiry_minutes)
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO proposals
                   (id, symbol, side, quantity, estimated_price, notional_usd, sector,
                    strategy_name, reasoning, stop_loss_price, target_price, status,
                    created_at, expires_at, decided_at, decided_by, decision_note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    proposal.proposal_id,
                    proposal.symbol,
                    proposal.side.value,
                    proposal.quantity,
                    proposal.estimated_price,
                    proposal.notional_usd,
                    proposal.sector,
                    proposal.strategy_name,
                    proposal.reasoning,
                    proposal.stop_loss_price,
                    proposal.target_price,
                    ProposalStatus.PENDING.value,
                    now.isoformat(),
                    expires_at.isoformat(),
                    None,
                    None,
                    None,
                ),
            )
            conn.commit()
        self.audit_log.write(
            "proposal_created",
            {"proposal_id": proposal.proposal_id, "symbol": proposal.symbol, "expires_at": expires_at.isoformat()},
        )
        return self.get(proposal.proposal_id)

    def get(self, proposal_id: str) -> StoredProposal | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return self._row_to_model(row) if row else None

    def list_pending(self, now: datetime | None = None) -> list[StoredProposal]:
        now = now or datetime.now(timezone.utc)
        self.expire_stale(now)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status = ? ORDER BY created_at", (ProposalStatus.PENDING.value,)
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def list_all(self, limit: int = 200) -> list[StoredProposal]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_model(r) for r in rows]

    def expire_stale(self, now: datetime | None = None) -> list[StoredProposal]:
        now = now or datetime.now(timezone.utc)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status = ? AND expires_at < ?",
                (ProposalStatus.PENDING.value, now.isoformat()),
            ).fetchall()
            ids = [row["id"] for row in rows]
            for proposal_id in ids:
                conn.execute(
                    "UPDATE proposals SET status=?, decided_at=?, decided_by=? WHERE id=?",
                    (ProposalStatus.EXPIRED.value, now.isoformat(), "system:expiry", proposal_id),
                )
            conn.commit()
        expired = []
        for proposal_id, row in zip(ids, rows):
            self.audit_log.write("proposal_expired", {"proposal_id": proposal_id, "symbol": row["symbol"]})
            expired.append(self.get(proposal_id))
        return expired

    def approve(self, proposal_id: str, approved_by: str, now: datetime | None = None) -> StoredProposal:
        now = now or datetime.now(timezone.utc)
        proposal = self._require_pending(proposal_id, now)
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE proposals SET status=?, decided_at=?, decided_by=? WHERE id=?",
                (ProposalStatus.APPROVED.value, now.isoformat(), approved_by, proposal_id),
            )
            conn.commit()
        self.audit_log.write(
            "proposal_approved", {"proposal_id": proposal_id, "approved_by": approved_by, "symbol": proposal.symbol}
        )
        return self.get(proposal_id)

    def reject(self, proposal_id: str, rejected_by: str, reason: str = "", now: datetime | None = None) -> StoredProposal:
        now = now or datetime.now(timezone.utc)
        proposal = self._require_pending(proposal_id, now)
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE proposals SET status=?, decided_at=?, decided_by=?, decision_note=? WHERE id=?",
                (ProposalStatus.REJECTED.value, now.isoformat(), rejected_by, reason, proposal_id),
            )
            conn.commit()
        self.audit_log.write(
            "proposal_rejected",
            {"proposal_id": proposal_id, "rejected_by": rejected_by, "reason": reason, "symbol": proposal.symbol},
        )
        return self.get(proposal_id)

    def approve_all_pending(self, approved_by: str, allow_bulk: bool, now: datetime | None = None) -> list[StoredProposal]:
        """Bulk approval does not exist by default (section 7a). Callers
        must pass allow_bulk=True explicitly (sourced from
        config/approval.yaml's allow_bulk_approve), and every bulk
        approval is logged as its own distinct event type, separate from
        individual proposal_approved records."""
        if not allow_bulk:
            raise BulkApprovalDisabledError("bulk approval is disabled by config/approval.yaml")

        now = now or datetime.now(timezone.utc)
        pending = self.list_pending(now)
        approved = []
        with closing(self._connect()) as conn:
            for proposal in pending:
                conn.execute(
                    "UPDATE proposals SET status=?, decided_at=?, decided_by=? WHERE id=?",
                    (ProposalStatus.APPROVED.value, now.isoformat(), approved_by, proposal.id),
                )
                approved.append(proposal.id)
            conn.commit()

        self.audit_log.write(
            "bulk_proposal_approval",
            {"approved_by": approved_by, "proposal_ids": approved, "count": len(approved)},
        )
        return [self.get(pid) for pid in approved]

    def _require_pending(self, proposal_id: str, now: datetime) -> StoredProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(f"no such proposal: {proposal_id}")
        if proposal.is_expired(now):
            self.expire_stale(now)
            raise ProposalExpiredError(f"proposal {proposal_id} expired at {proposal.expires_at}")
        if proposal.status != ProposalStatus.PENDING:
            raise ProposalAlreadyDecidedError(f"proposal {proposal_id} is already {proposal.status.value}")
        return proposal

    def _row_to_model(self, row: sqlite3.Row) -> StoredProposal:
        return StoredProposal(
            id=row["id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=row["quantity"],
            estimated_price=row["estimated_price"],
            notional_usd=row["notional_usd"],
            sector=row["sector"],
            strategy_name=row["strategy_name"],
            reasoning=row["reasoning"],
            stop_loss_price=row["stop_loss_price"],
            target_price=row["target_price"],
            status=ProposalStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
            decided_by=row["decided_by"],
            decision_note=row["decision_note"],
        )
