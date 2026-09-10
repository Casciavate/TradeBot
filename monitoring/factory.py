"""Builds a configured AlertRouter from config/monitoring.yaml.

Kept separate from alerts.py so that module stays free of any config
dependency and can be used standalone in tests.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from monitoring.alerts import (
    AlertChannel,
    AlertRouter,
    AlertSeverity,
    ConsoleAlertChannel,
    EmailAlertChannel,
)
from monitoring.audit_log import AuditLog

if TYPE_CHECKING:  # pragma: no cover -- import-cycle avoidance
    from config.schema import AppConfig


def build_alert_router(config: "AppConfig", state_dir: str = "state") -> AlertRouter:
    monitoring = config.monitoring
    channels: list[AlertChannel] = []

    if monitoring.console_alerts:
        channels.append(ConsoleAlertChannel())

    if monitoring.email.enabled:
        channels.append(
            EmailAlertChannel(
                host=monitoring.email.smtp_host,
                port=monitoring.email.smtp_port,
                sender=monitoring.email.sender,
                recipients=list(monitoring.email.recipients),
                username=monitoring.email.username,
                password_env_var=monitoring.email.password_env_var,
                use_starttls=monitoring.email.use_starttls,
                min_severity=AlertSeverity(monitoring.email.min_severity),
            )
        )

    return AlertRouter(
        audit_log=AuditLog(f"{state_dir}/alerts.log"),
        channels=channels,
        throttle_seconds=monitoring.alert_throttle_seconds,
    )


def build_default_alert_router(state_dir: str = "state") -> AlertRouter:
    """Best-effort router for standalone CLI tools.

    Falls back to an audit-log + console router if config cannot be loaded
    at all. The kill switch in particular has to keep working when the
    config is broken -- refusing to halt trading because monitoring.yaml
    has a typo would be exactly the wrong failure mode.
    """
    try:
        from config.loader import load_config

        return build_alert_router(load_config(log_changes=False), state_dir=state_dir)
    except Exception as exc:  # noqa: BLE001 -- a broken config must not disable the kill switch
        print(f"warning: could not load config for alerting ({exc}); using console alerts only")
        return AlertRouter(
            audit_log=AuditLog(f"{state_dir}/alerts.log"),
            channels=[ConsoleAlertChannel()],
            throttle_seconds=0,
        )
