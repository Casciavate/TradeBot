"""The only place in this codebase that reads LIVE_TRADING. No config
file, no strategy code, and no risk_gate code can set this -- it must be
an environment variable set outside the process by whoever launches it
(section 0, rule 1). Connecting defaults to the paper port every time this
variable is unset or anything other than exactly "true"."""
from __future__ import annotations

import os
from dataclasses import dataclass

from config.schema import ConnectionConfig

LIVE_TRADING_ENV_VAR = "LIVE_TRADING"


def is_live_trading_enabled() -> bool:
    return os.environ.get(LIVE_TRADING_ENV_VAR, "").strip().lower() == "true"


@dataclass(frozen=True)
class ConnectionTarget:
    host: str
    port: int
    client_id: int
    is_live: bool


def resolve_connection_target(config: ConnectionConfig) -> ConnectionTarget:
    is_live = is_live_trading_enabled()
    port = config.live_port if is_live else config.paper_port
    return ConnectionTarget(host=config.host, port=port, client_id=config.client_id, is_live=is_live)


def connect(config: ConnectionConfig):
    """Opens a real ib_async connection. Only ever called from a script
    that assembles the live/paper pipeline -- never imported by
    signal_layer, risk_gate, or approval_layer."""
    from ib_async import IB

    target = resolve_connection_target(config)
    ib = IB()
    ib.connect(target.host, target.port, clientId=target.client_id)
    return ib, target
