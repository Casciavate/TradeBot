"""Vercel entrypoint for the read-only status page.

Exports a module-level `app` FastAPI ASGI object -- the exact convention
Vercel's Python/FastAPI builder scans for (named in this repo's own build
error: https://vercel.com/docs/frameworks/backend/fastapi#exporting-the-fastapi-application).

This is NOT the control center. No approve/reject, no kill switch or
circuit breaker control, no broker connection -- see docs/UI.md's
"Should this run on Vercel?" and docs/DEPLOY.md for why none of that can
work honestly on a serverless platform: no persistent local disk, no
long-lived broker socket. What this serves instead: a read-only view
built from placeholder account data, explicitly labeled on the page
itself as a disconnected preview, not a live system.

This file touches disk nowhere, on purpose. Vercel's filesystem is
read-only outside /tmp; config.loader.load_config()'s default behavior
writes a risk-config audit log on every call, which would crash every
request here, so it's called with log_changes=False. No AlertRouter,
KillSwitch, or CircuitBreaker is wired in -- passing real instances
pointed at a filesystem that resets on every cold start would silently
misrepresent halt state as confirmed-clear when nothing actually checked
it, which is exactly what the required `demo_notice` below exists to
prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Vercel's Python runtime's working directory / sys.path setup for a
# nested api/ entrypoint is not something this build could verify live
# (see docs/DEPLOY.md's note on unverified Vercel-specific behavior) --
# this makes repo-root imports (config, monitoring, risk_gate) work
# regardless of that, the same defensive pattern scripts/_bootstrap.py
# uses for the CLI entry points.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.loader import load_config  # noqa: E402
from monitoring.status_dashboard import build_status_app  # noqa: E402
from risk_gate.models import PortfolioState  # noqa: E402

_config = load_config(log_changes=False)


def _placeholder_portfolio() -> PortfolioState:
    """No broker connection and no persistent state exist on this
    deployment -- there is nothing to reconcile a real snapshot from.
    Same fallback scripts/run_control_center.py and
    scripts/run_status_dashboard.py already use without a live IBKR
    connection, so the page's own "Placeholder account size" banner is
    telling the truth here too."""
    capital = _config.account.starting_capital_usd
    return PortfolioState(equity=capital, peak_equity=capital, cash=capital)


app = build_status_app(
    config=_config,
    portfolio_provider=_placeholder_portfolio,
    kill_switch=None,
    circuit_breaker=None,
    alert_router=None,
    demo_notice=(
        "Read-only preview deployment. Not connected to any live trading "
        "system, broker, or kill switch -- this page cannot show whether "
        "trading is actually halted anywhere. See docs/DEPLOY.md for the "
        "real, always-on deployment."
    ),
)
