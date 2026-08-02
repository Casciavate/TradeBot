"""The minimal broker interface OrderManager needs. ib_async.IB()
satisfies this once connected; tests use a lightweight fake implementing
the same three calls, with no network/event-loop dependency."""
from __future__ import annotations

from typing import Any, Protocol


class BrokerClient(Protocol):
    def placeOrder(self, contract: Any, order: Any) -> Any: ...

    def positions(self, account: str = "") -> list: ...

    def isConnected(self) -> bool: ...
