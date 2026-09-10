# Monitoring & alerting

What the system records, what it shouts about, and where to look when
something has gone wrong. This covers section 8 of the build spec.

## Everything is written down

Four append-only JSONL logs under `state/`. They are the audit trail;
nothing truncates or rewrites them in place.

| File | Written by | Contains |
|------|-----------|----------|
| `state/signal_audit.log` | `monitoring.SignalLog` | every signal generated, and what became of it |
| `state/risk_gate_audit.log` | `risk_gate.RiskGate` | every pass/block decision and the reason |
| `state/approval_audit.log` | `approval_layer.ProposalStore` | proposal created / approved / rejected / expired |
| `state/execution_audit.log` | `execution_layer.OrderManager` | order submitted, state changed, submission failed |
| `state/alerts.log` | `monitoring.AlertRouter` | every alert raised, delivered or not |
| `state/config_audit.log` | `config.loader` | timestamped diffs of risk-relevant config changes |

Signals are logged even when they never become a proposal. A signal that
sizes to zero shares is recorded with `outcome: sized_out`, one blocked by
risk_gate with `outcome: blocked`. That matters because it lets you judge
the strategies' proposal quality separately from what you chose to
approve, which is the whole point of keeping the approval log too.

## Alerts

`monitoring.AlertRouter` fans an alert out to configured channels. The
four events the build spec names as alertable are all wired:

| Event | Raised by | Severity |
|-------|----------|----------|
| Circuit breaker tripped | `risk_gate.CircuitBreaker.trip` | CRITICAL |
| Kill switch engaged | `risk_gate.KillSwitch.engage` | CRITICAL |
| Order rejected by IBKR | `execution_layer.OrderManager` | CRITICAL |
| Broker connection lost | `execution_layer.ConnectionWatchdog` | CRITICAL |
| Order submission failed | `execution_layer.OrderManager` | CRITICAL |
| Position reconciliation mismatch | `execution_layer.reconcile_positions` | CRITICAL |
| Circuit breaker reset, kill switch disengaged, connection restored | as above | WARNING |

Three rules the alerting layer is built around, each with a test:

1. **A failing channel never breaks the thing that raised the alert.** If
   SMTP hangs while the kill switch is being engaged, the kill switch
   still engages. The flag file is written first; channel exceptions are
   caught and recorded as `alert_channel_failed`.
2. **Every alert is always written to `state/alerts.log`**, whatever the
   channels do. Delivery is a convenience on top of the durable record.
3. **Throttling suppresses delivery, never the record.** Repeat alerts
   with the same kind and dedup key inside `alert_throttle_seconds` are
   logged but not re-delivered, so a per-cycle connection check raises one
   alert rather than one per cycle.

### Channels

Console is on by default, so alerting is never silently off. Email is
opt-in via `config/monitoring.yaml`. There is deliberately **no password
field in that file** -- the SMTP password is read at send time from the
environment variable named by `password_env_var` (default
`TRADEBOT_SMTP_PASSWORD`), so no credential lands in the repo or in the
audit log. Enabling email without an SMTP host, sender, and recipients is
a config validation error rather than a channel that silently cannot
deliver.

## Dashboards

Two separate apps on two separate ports, deliberately:

- **Approval dashboard** (`scripts/run_approval_dashboard.py`, port 8000)
  is the only place a human authorises an order.
- **Status dashboard** (`scripts/run_status_dashboard.py`, port 8001) is
  read-only: positions, daily P&L, risk limit headroom, halt state, recent
  alerts. It exposes only GET routes and has no import path to
  `execution_layer` -- both enforced by tests. A JSON view of the same
  data is at `/api/status`.

Keeping them apart means a stray click on the page you leave open to watch
the account can never place a trade.

## Daily summary

`python scripts/daily_summary.py [YYYY-MM-DD] [--email]`

P&L, positions, risk limit usage, activity counts, risk_gate blocks
tallied by reason, and any circuit breaker trips. It is built from the
audit logs plus one portfolio snapshot, so any past day can be
regenerated from the logs alone.

To get it automatically, schedule it -- e.g. a cron entry after the US
close:

```
30 21 * * 1-5 cd /path/to/TradeBot && .venv/bin/python scripts/daily_summary.py --email
```

## Risk limit headroom

`monitoring.compute_risk_usage` reports how much of each configured limit
is consumed: largest position, largest sector exposure, daily loss,
drawdown from peak, and gross leverage. It reads the same
`config/risk_limits.yaml` values `risk_gate` enforces against, so the two
cannot disagree about what the limit is.

It is a **display only** and is not in the order path. Enforcement lives
in `risk_gate/limits.py`. Utilization is deliberately not clipped at 100%,
so a breach reads as e.g. 150% and you can see how far over it went.

## Where to look when something breaks

- **Trading has stopped.** Check the status dashboard banner, or
  `scripts/kill_switch_cli.py status` and `scripts/circuit_breaker_cli.py
  status`. A tripped breaker stays tripped until a human resets it; that
  is intended.
- **An order did not go through.** `state/execution_audit.log` for the
  order's state history, `state/alerts.log` for the rejection alert.
- **A proposal never appeared.** `state/signal_audit.log` shows whether a
  signal existed at all and what happened to it, then
  `state/risk_gate_audit.log` for the blocking reason.
- **Local and IBKR positions disagree.** That raises a CRITICAL
  reconciliation alert and is never auto-corrected. IBKR is ground truth;
  a human resolves the difference.

## Known gaps

- The status dashboard and daily summary currently fall back to a
  placeholder portfolio derived from `config/account.yaml` when no broker
  connection is wired in. Both say so on their face. Wire a reconciled
  IBKR account snapshot in before paper trading, or every percentage on
  those pages is measured against a made-up equity figure.
- There is no SMS or Slack channel. `AlertChannel` is a small protocol
  (`name` plus `send(alert)`), so adding one is a new class and a config
  entry, not a change to the router.
- The connection watchdog is a poller: it must be called each cycle by
  whatever is running. It never reconnects on its own, because a silent
  auto-reconnect could mask an order whose fate is unknown.
