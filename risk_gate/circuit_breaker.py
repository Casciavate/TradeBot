"""Persistent circuit-breaker latch. Once tripped (daily loss or drawdown
limit breached), it stays tripped -- surviving process restarts -- until a
human explicitly calls reset(). A portfolio snapshot recovering above the
threshold on its own must NOT silently clear this."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_PATH = Path(__file__).parent.parent / "state" / "circuit_breaker.json"


class CircuitBreaker:
    def __init__(self, path: str | Path = DEFAULT_STATE_PATH):
        self.path = Path(path)

    def is_tripped(self) -> bool:
        return self._read() is not None

    def trip(self, reason: str) -> None:
        if self.is_tripped():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"reason": reason, "tripped_at": datetime.now(timezone.utc).isoformat()})
        )

    def reset(self, cleared_by: str) -> dict | None:
        info = self._read()
        self.path.unlink(missing_ok=True)
        return info

    def info(self) -> dict | None:
        return self._read()

    def _read(self) -> dict | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())
