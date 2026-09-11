"""Local control center: one page to watch the account, approve trades,
and halt the system.

This package is an *assembly* layer. It composes `approval_layer` (write)
and `monitoring` (read) into a single local web UI. Like
`scripts/run_approval_dashboard.py` before it, it deliberately does NOT
import `execution_layer` -- the callback that turns an approved proposal
into an IBKR order is injected by the launch script, so the boundary
"nothing reaches the broker except through a recorded human approval"
still holds structurally, not just by convention.
"""
from control_center.app import build_control_center

__all__ = ["build_control_center"]
