# Control center UI

One local web app: watch the account, approve or reject proposed trades,
and halt the system. `scripts/run_control_center.py`, default port 8000.

This replaces the earlier two-dashboard setup
(`run_approval_dashboard.py` + `run_status_dashboard.py`) with a single
app that has everything in one place, while keeping the same boundaries.
The two old scripts still work if you'd rather keep approvals and status
on separate processes/ports.

## Pages

- **Overview** (`/`) -- equity, today's P&L, drawdown, positions, risk
  limit headroom, and the last dozen events. The one-glance page.
- **Proposals** (`/proposals`) -- every pending proposal with its
  reasoning, entry/stop/target, and expiry, plus approve/reject buttons.
  Recent decisions below it.
- **Activity** (`/activity`) -- the full merged audit-log feed (signals,
  risk_gate decisions, proposals, orders, alerts, config changes),
  filterable by category. This reads the same JSONL files described in
  `docs/MONITORING.md`; it renders them, it does not replace them.
- **Controls** (`/controls`) -- kill switch and circuit breaker, plus the
  equivalent CLI commands for when this UI isn't running.

## Why this doesn't compromise the approval boundary

`control_center/app.py` never imports `execution_layer`. The only thing
it can do with an approved proposal is call an `on_approved` callback that
is *injected* by `scripts/run_control_center.py` -- the assembly script,
same pattern `run_approval_dashboard.py` used before it. A test
(`tests/test_live_trading_boundary.py`) fails the build if that import
ever gets added. Approving a proposal always writes the decision to
`state/approval_audit.log` first; only then does the callback run, so a
crash mid-submission still leaves a human decision on the record instead
of an order with no trace of who authorised it.

Re-enabling trading is deliberately not a single click. Engaging the kill
switch is -- halting is always the safe direction -- but disengaging it,
and resetting a tripped circuit breaker, both require typing
`RESUME TRADING` into a confirmation field. A double click or a stray tap
cannot resume trading; only a person who reads the prompt can.

## Access control

Binds to `127.0.0.1` by default: only processes on the same machine can
reach it, and no token is required. This UI can authorise real orders, so
binding it to any other address requires an access token, read from the
`TRADEBOT_UI_TOKEN` environment variable (configurable in
`config/ui.yaml`). Starting on a non-loopback host with no token set
raises at boot rather than quietly serving an unauthenticated
trade-approval page to the network:

```
export TRADEBOT_UI_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

A shared token over plain HTTP is weak authentication -- it exists to
make accidental exposure fail loudly, not to make real exposure safe.
For anything beyond a trusted LAN (a home network, a VPN you already
trust), put a reverse proxy with TLS and real authentication in front of
it. Do not port-forward this to the public internet as-is.

## Should this run on Vercel?

No. Skip it, for three separable reasons, not one:

1. **It needs a live TWS/Gateway TCP connection.** `execution_layer`
   connects via `ib_async` to a socket on `127.0.0.1:7497` (paper) or
   `:7496` (live) -- the IBKR desktop app or Gateway running on the same
   machine or LAN. Vercel functions are stateless, short-lived, and have
   no route to that socket; there is no version of this architecture
   where a serverless function on Vercel's infrastructure reaches your
   local TWS session.
2. **State needs to persist and be trusted.** The kill switch is a file
   on disk that other processes check for existence. The circuit breaker
   is a JSON latch that must survive restarts. The proposal store is a
   local SQLite file. None of that maps onto stateless serverless
   compute without adding a database and a message layer that this
   system's whole design (a human-in-the-loop approval boundary you can
   physically point to as one file, one script) was built to avoid.
3. **A trade-approval endpoint should not be internet-facing by
   default.** Every extra network hop between "risk_gate passed this"
   and "a human clicked approve" is a hop where something could go wrong
   -- accidental exposure, a compromised token, a platform-side bug.
   Local-first with a locked-down remote-access option (Tailscale,
   WireGuard, an SSH tunnel) if you need it from your phone keeps that
   surface as small as the trading system itself requires.

If the actual want is "see this from my phone" or "keep this running
without my laptop staying on," the right shape is an always-on host --
your own machine, a home server, or a small VM -- running this app
unmodified alongside a headless IB Gateway, reachable over Tailscale or a
reverse proxy with TLS. `deploy/` in this repo sets exactly that up
(Docker Compose, both services, documented and verified end to end); see
`docs/DEPLOY.md` for the full runbook. Vercel isn't in scope for either
half of that -- it can't hold the live broker connection or the local
safety-critical state either one.

## Configuration

`config/ui.yaml`:

```yaml
host: 127.0.0.1
port: 8000
operator_name: ""       # pre-fills the approve/reject forms; convenience only
token_env_var: TRADEBOT_UI_TOKEN
```

There is no token field in the file itself -- see Access control above.

## Known gaps

- `portfolio_provider` in `scripts/run_control_center.py` currently falls
  back to a placeholder built from `config/account.yaml`'s starting
  capital when no IBKR connection is live. The overview page says so.
  Wire in a reconciled account snapshot before paper trading.
- The session cookie is a plain shared secret with no expiry and no
  per-operator identity -- fine for "one household, one operator,"
  wrong for anything with more than one approver. Add real
  authentication (even just separate named tokens with distinct log
  entries) before more than one person uses this.
- No CSRF token on the POST forms. On a `127.0.0.1`-only deployment with
  no other site able to reach it, that is a low-risk gap; it stops being
  low-risk the moment this is reachable from anywhere else, which is one
  more reason not to expose it further than described above.
