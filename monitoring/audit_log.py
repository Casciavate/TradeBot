"""Append-only, timestamped JSONL audit log. Used for risk_gate decisions,
config-change diffs, and approval/rejection/expiry records. This is the
system's audit trail -- never truncate or rewrite it in place."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event_type: str, payload: dict, ts: datetime | None = None) -> dict:
        """`ts` defaults to real wall-clock time. Callers that already have
        a meaningful timestamp -- the backtest engine's simulated bar date,
        or an alert's `raised_at` -- should pass it explicitly, or every
        record from a multi-year backtest replayed in a few seconds of
        wall-clock time would land under today's date instead of the
        simulated one."""
        record = {
            "ts": (ts or datetime.now(timezone.utc)).isoformat(),
            "event_type": event_type,
            **payload,
        }
        line = json.dumps(record, sort_keys=True, default=str)
        with self._lock, open(self.path, "a") as f:
            f.write(line + "\n")
        return record

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            return [json.loads(line) for line in f if line.strip()]
