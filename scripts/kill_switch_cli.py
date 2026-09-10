#!/usr/bin/env python3
"""Manual kill-switch control, independent of the rest of the running
system -- this must work even if every other process is dead or hung.

Usage:
    python scripts/kill_switch_cli.py engage "reason for halting"
    python scripts/kill_switch_cli.py disengage
    python scripts/kill_switch_cli.py status
"""
from __future__ import annotations

import _bootstrap  # noqa: F401 -- puts the repo root on sys.path

import sys

from monitoring.factory import build_default_alert_router
from risk_gate.kill_switch import KillSwitch


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    # Engaging/disengaging raises a section-8 alert. If alerting is
    # misconfigured the router degrades to console-only rather than
    # preventing the halt.
    ks = KillSwitch(alert_router=build_default_alert_router())
    command = argv[0]

    if command == "engage":
        reason = argv[1] if len(argv) > 1 else "manually engaged via CLI"
        ks.engage(reason)
        print(f"KILL SWITCH ENGAGED: {reason}")
        return 0

    if command == "disengage":
        ks.disengage()
        print("Kill switch disengaged.")
        return 0

    if command == "status":
        if ks.is_engaged():
            print(f"ENGAGED: {ks.reason()}")
        else:
            print("disengaged")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
