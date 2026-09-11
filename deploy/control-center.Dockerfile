# Container image for the control center only. It does NOT contain
# backtest_engine's heavy dependencies (vectorbt, numba, scikit-learn,
# matplotlib) -- see requirements-control-center.txt for why.
#
# Build context must be the repo root (see docker-compose.yml's
# `build: context: .. `), because this needs the whole package tree
# (control_center/, approval_layer/, config/, monitoring/, risk_gate/,
# execution_layer/, data_layer/, scripts/) -- these packages import each
# other, so a partial copy would break at runtime, not at build time.
FROM python:3.11-slim AS base

# Runs as a non-root user. This container holds no IBKR credentials of
# its own (those live in the ib-gateway container -- see
# docs/DEPLOY.md's Credentials section) but keeps to the same principle
# regardless.
RUN groupadd --gid 1000 tradebot && useradd --uid 1000 --gid tradebot --create-home tradebot

WORKDIR /app

COPY deploy/requirements-control-center.txt /app/deploy/requirements-control-center.txt
RUN pip install --no-cache-dir -r /app/deploy/requirements-control-center.txt

# Only what scripts/run_control_center.py and its imports actually need
# at runtime -- not backtest_engine, signal_layer, data/, docs/, or tests/.
COPY control_center/ /app/control_center/
COPY approval_layer/ /app/approval_layer/
COPY config/ /app/config/
COPY monitoring/ /app/monitoring/
COPY risk_gate/ /app/risk_gate/
COPY execution_layer/ /app/execution_layer/
COPY data_layer/ /app/data_layer/
COPY scripts/_bootstrap.py /app/scripts/_bootstrap.py
COPY scripts/run_control_center.py /app/scripts/run_control_center.py

# Deployment-specific config: talks to the ib-gateway container over the
# docker network instead of 127.0.0.1:7497, and binds the UI to 0.0.0.0
# so Docker's port publishing (and Caddy, if used) can reach it. See
# config-overrides/README in docs/DEPLOY.md for why these are separate
# files rather than edits to the repo's own config/*.yaml.
COPY deploy/config-overrides/connection.yaml /app/config/connection.yaml
COPY deploy/config-overrides/ui.yaml /app/config/ui.yaml

# state/ holds the kill switch flag, the circuit breaker latch, the
# proposal SQLite database, and every audit log -- this is the data a
# volume mount (see docker-compose.yml) must persist across container
# restarts, or the kill switch's "survives a restart" guarantee is a lie.
RUN mkdir -p /app/state && chown -R tradebot:tradebot /app

USER tradebot

EXPOSE 8000

CMD ["python", "scripts/run_control_center.py"]
