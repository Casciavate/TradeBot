"""Access control for the control center.

The approval dashboard is the only thing standing between a signal and a
real order, so binding it to anything other than loopback is treated as a
deliberate, guarded act:

- On a loopback address (127.0.0.1, ::1, localhost) no token is required.
  Only processes on the same machine can reach it.
- On any other address a token is REQUIRED, read from an environment
  variable. Starting without one raises at boot rather than quietly
  serving an unauthenticated trade-approval UI to the network.

A shared token over plain HTTP is weak authentication. It exists to make
accidental exposure fail loudly, not to make exposure safe. Anything
beyond a trusted LAN wants a reverse proxy with TLS and real auth in
front -- see docs/UI.md.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0.localhost"}
SESSION_COOKIE = "tradebot_ui"


class InsecureBindError(RuntimeError):
    """Raised when the UI would be served to a non-loopback address with
    no token set."""


def is_loopback(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


@dataclass(frozen=True)
class AccessPolicy:
    required: bool
    token: str | None

    def matches(self, presented: str | None) -> bool:
        if not self.required:
            return True
        if not presented or not self.token:
            return False
        return secrets.compare_digest(presented, self.token)


def resolve_access_policy(host: str, token_env_var: str) -> AccessPolicy:
    token = os.environ.get(token_env_var, "").strip() or None

    if is_loopback(host):
        # A token on loopback is optional but honoured if set.
        return AccessPolicy(required=token is not None, token=token)

    if token is None:
        raise InsecureBindError(
            f"refusing to serve the control center on {host!r} with no access token: "
            f"this UI can authorise real orders. Set ${token_env_var} to a long random "
            "value, or bind to 127.0.0.1. Note that a token over plain HTTP is weak "
            "auth -- put TLS and real authentication in front of it for anything "
            "beyond a trusted network."
        )

    return AccessPolicy(required=True, token=token)


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)
