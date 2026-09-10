#!/usr/bin/env python3
"""Manual circuit-breaker control. A tripped breaker (daily loss or
drawdown limit breached) stays tripped until a human runs the reset
command here -- it never clears itself.

Usage:
    python scripts/circuit_breaker_cli.py status
    python scripts/circuit_breaker_cli.py reset "your name or note"
"""
from __future__ import annotations

import _bootstrap  # noqa: F401 -- puts the repo root on sys.path

import sys

from monitoring.factory import build_default_alert_router
from risk_gate.circuit_breaker import CircuitBreaker


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    cb = CircuitBreaker(alert_router=build_default_alert_router())
    command = argv[0]

    if command == "status":
        if cb.is_tripped():
            info = cb.info() or {}
            print(f"TRIPPED at {info.get('tripped_at')}: {info.get('reason')}")
        else:
            print("not tripped")
        return 0

    if command == "reset":
        cleared_by = argv[1] if len(argv) > 1 else "unspecified"
        info = cb.reset(cleared_by=cleared_by)
        if info is None:
            print("Circuit breaker was not tripped; nothing to reset.")
        else:
            print(f"Circuit breaker reset by {cleared_by}. Was tripped for: {info.get('reason')}")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
