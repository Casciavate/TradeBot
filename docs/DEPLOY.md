# Deploying: an always-on host with a live IBKR connection

`deploy/` runs this system unmodified on a machine that stays on, with a
real, persistent connection to Interactive Brokers -- the thing Vercel
(or any serverless platform) structurally cannot do, since a serverless
function holds no long-lived TCP session and has no persistent local
disk. See `docs/UI.md`'s "Should this run on Vercel?" for why.

This is two containers on one host, talking over a private Docker
network:

- **`ib-gateway`** -- headless IB Gateway, using the image documented at
  <https://github.com/gnzsnz/ib-gateway-docker>. This is a third-party
  project (MIT-licensed, actively maintained as of the version checked
  while building this), not IBKR's own software -- it automates the
  TWS/Gateway login dialogs (via [IBC](https://github.com/IbcAlpha/IBC))
  so Gateway can run without a human clicking through a GUI every time.
  Review its current README yourself before trusting it with real
  credentials; this repo pins `ghcr.io/gnzsnz/ib-gateway:stable` in
  `deploy/docker-compose.yml`, but re-check that tag's current status
  before going live.
- **`control-center`** -- this repo's control center, built from
  `deploy/control-center.Dockerfile`, reaching `ib-gateway` over the
  private `trader` docker network rather than `127.0.0.1`.

Every claim below about `ib-gateway-docker`'s environment variables,
default ports, and internal `socat` port-forwarding behavior was verified
by cloning that repository and reading its README, `docker-compose.yml`,
and `run_socat.sh`/`common.sh` directly -- not assumed from training
data. Re-verify against its current `README.md` before you rely on it,
since third-party projects change.

## What you need first

- A machine that stays on: a small VM (a $5-6/month box from
  DigitalOcean, Hetzner, or similar; a free-tier Oracle Cloud instance;
  an AWS Lightsail instance) or your own always-on hardware (a home
  server, a NAS that runs Docker). Docker and Docker Compose installed on
  it.
- Your IBKR username and password. 2FA (IBKR's Secure Login System) still
  applies -- `ib-gateway-docker` automates the surrounding dialogs, not
  the 2FA approval itself. You will need to approve a push notification
  on your phone at least once, and periodically thereafter depending on
  the settings below.
- A decision on how you'll reach the control center remotely: a private
  network you control (Tailscale is the lowest-friction option: install
  it on the VM, then reach the control center at the VM's Tailscale
  address with no public port needed at all) or a domain name plus the
  optional Caddy TLS profile in `deploy/docker-compose.yml`. Don't skip
  this -- see Security below.

## Steps

1. Copy the repo (or just `deploy/` plus the packages it builds from) to
   the host. From this branch:
   ```
   git clone https://github.com/Casciavate/TradeBot.git
   cd TradeBot
   git checkout claude/ibkr-trading-bot-build-qwm5d1
   ```
2. `cd deploy && cp .env.example .env`, then edit `.env`:
   - `TWS_USERID` / `TWS_PASSWORD` -- your IBKR credentials.
   - `TRADING_MODE=paper` -- leave this as paper. Read
     `docs/RISK_ARCHITECTURE.md` in full, and mean it, before ever
     changing this to `live`.
   - `TRADEBOT_UI_TOKEN` -- generate one:
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - Everything else has a documented default in `.env.example`.
3. `docker compose up -d`
4. `docker compose logs -f ib-gateway` and watch the first login. IBC
   will send the 2FA push to your phone; approve it. Once you see it
   settle into a steady "listening" state (no more login-related lines
   scrolling), it's up.
5. `docker compose logs -f control-center` -- look for
   `control center on http://0.0.0.0:8000` and no `could not connect to
   TWS/Gateway` line. If you see the latter, `ib-gateway` likely isn't
   finished logging in yet; give it another minute and check again.
6. Reach it: over Tailscale, `http://<the-vm's-tailscale-address>:8000`;
   otherwise `docker compose --profile tls up -d` after editing
   `deploy/Caddyfile` with your domain, then `https://your-domain`.
   Either way, you'll land on `/login` and need the
   `TRADEBOT_UI_TOKEN` value from your `.env`.

## Before you trust what it shows you

- `config/account.yaml`'s `starting_capital_usd` is still a placeholder
  (`is_placeholder: true`). The overview page says so. Every
  percentage-based number is meaningless until you fix that.
- `scripts/run_control_center.py`'s `portfolio_provider` still returns
  that placeholder snapshot, not a reconciled IBKR account snapshot, even
  once `ib-gateway` is connected. Wiring in a real snapshot (via
  `execution_layer.reconciliation` and IBKR's own reported positions) is
  the next piece of work, not something this deployment does for you.
- Nothing here changes the approval boundary: `control_center/app.py`
  still has no import of `execution_layer`, and an order still requires
  you to click Approve. Connecting `ib-gateway` makes that click
  meaningful (there's now a broker on the other end); it does not change
  who has to click it.

## Credentials

- `TWS_USERID`/`TWS_PASSWORD` go only into the `ib-gateway` container's
  environment. `control-center` never sees them -- it only ever talks to
  `ib-gateway` over the TWS API socket, the same protocol/boundary this
  app already used for local TWS.
- If you'd rather not put a plaintext password in `.env`, the upstream
  image supports Docker secrets (`TWS_PASSWORD_FILE`) -- see its
  [Credentials section](https://github.com/gnzsnz/ib-gateway-docker#credentials).
- `deploy/.env` is gitignored. Never commit it.

## Security

The IBKR API protocol itself is an unauthenticated, unencrypted raw TCP
socket -- this is upstream's own stated reason for keeping `ib-gateway`
off any published port entirely (`deploy/docker-compose.yml` follows
that: no `ports:` on `ib-gateway`, reachable only from `control-center`
over the private `trader` network).

`control-center` is reachable from outside the host, gated by
`TRADEBOT_UI_TOKEN`. That token is a shared secret checked with a
constant-time comparison (`control_center/auth.py`), which is reasonable
authentication but not a substitute for network-level protection:

- **Prefer Tailscale or WireGuard.** No public port at all; the token
  becomes a second layer, not the only one.
- **If you use the Caddy TLS profile instead**, you get HTTPS (so the
  token isn't sent in the clear) but the port is genuinely public --
  add a host firewall rule limiting who can reach 8000/443 if you want
  defense in depth beyond the token.
- **Never skip both.** A bare token over plain HTTP on a publicly
  reachable port is the one combination to avoid.

Re-enabling trading through the UI (disengaging the kill switch,
resetting the circuit breaker) still requires typing the confirmation
phrase described in `docs/UI.md` -- that protection is unrelated to and
unaffected by any of the above.

## State and backups

`deploy/docker-compose.yml` mounts a `tradebot_state` volume at
`/app/state` in the `control-center` container -- this is where the kill
switch flag, the circuit breaker latch, the proposal database, and every
audit log live. `docker volume` on this host is now the durable store for
all of that; back it up like you would any other database (`docker run
--rm -v tradebot_state:/state -v $(pwd):/backup alpine tar czf
/backup/tradebot-state-$(date +%F).tar.gz -C /state .` is a reasonable
one-liner). `ib_gateway_settings` similarly persists IB Gateway's own
window/API settings across container recreation -- it never contains
your password.

## What this does not do

- **Does not add a persistent trade history or backtest runner to the
  host.** `backtest_engine` and its heavier dependencies
  (`vectorbt`/`numba`/`scikit-learn`) are deliberately excluded from
  `control-center`'s image (`deploy/requirements-control-center.txt`) --
  run backtests locally or in a separate environment.
- **Does not make `LIVE_TRADING=true` any easier to reach.**
  `execution_layer/connection.py` is still the only file that reads that
  variable, and it's not referenced anywhere in `deploy/`.
- **Does not replace the need to read `docs/RISK_ARCHITECTURE.md` and
  `docs/MONITORING.md`.** Hosting this durably is infrastructure; it
  doesn't substitute for the paper-trading observation period and
  backtest review the build spec calls for before any of this touches
  real money.
