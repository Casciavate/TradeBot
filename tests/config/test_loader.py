from __future__ import annotations

import shutil

from config.loader import load_config


def _copy_config_dir(src, dst):
    shutil.copytree(src, dst)


def test_first_load_logs_full_snapshot_as_a_change(tmp_path):
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    state_dir = tmp_path / "state"

    load_config(config_dir=config_dir, state_dir=state_dir)

    audit_path = state_dir / "config_audit.log"
    assert audit_path.exists()
    lines = audit_path.read_text().strip().splitlines()
    sections_logged = set()
    import json

    for line in lines:
        record = json.loads(line)
        assert record["event_type"] == "config_change"
        assert record["first_load"] is True
        sections_logged.add(record["section"])
    assert sections_logged == {"risk_limits", "account"}


def test_changing_a_risk_limit_produces_a_diffed_log_entry(tmp_path):
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    state_dir = tmp_path / "state"

    load_config(config_dir=config_dir, state_dir=state_dir)

    risk_limits_path = config_dir / "risk_limits.yaml"
    text = risk_limits_path.read_text().replace(
        "max_position_pct_of_equity: 0.08", "max_position_pct_of_equity: 0.05"
    )
    risk_limits_path.write_text(text)

    load_config(config_dir=config_dir, state_dir=state_dir)

    import json

    records = [json.loads(line) for line in (state_dir / "config_audit.log").read_text().strip().splitlines()]
    change_records = [r for r in records if r["section"] == "risk_limits" and not r["first_load"]]
    assert len(change_records) == 1
    diff = change_records[0]["changes"]["max_position_pct_of_equity"]
    assert diff == {"old": 0.08, "new": 0.05}


def test_unchanged_config_produces_no_new_log_entries(tmp_path):
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    state_dir = tmp_path / "state"

    load_config(config_dir=config_dir, state_dir=state_dir)
    first_count = len((state_dir / "config_audit.log").read_text().strip().splitlines())

    load_config(config_dir=config_dir, state_dir=state_dir)
    second_count = len((state_dir / "config_audit.log").read_text().strip().splitlines())

    assert first_count == second_count


def test_invalid_leverage_for_cash_account_is_rejected(tmp_path):
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    state_dir = tmp_path / "state"

    risk_limits_path = config_dir / "risk_limits.yaml"
    text = risk_limits_path.read_text().replace("max_leverage: 1.0", "max_leverage: 2.0")
    risk_limits_path.write_text(text)

    import pytest

    with pytest.raises(Exception):
        load_config(config_dir=config_dir, state_dir=state_dir)


def test_monitoring_section_loads_from_yaml(tmp_path):
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    state_dir = tmp_path / "state"

    config = load_config(config_dir=config_dir, state_dir=state_dir)

    assert config.monitoring.console_alerts is True
    assert config.monitoring.email.enabled is False
    assert config.monitoring.status_dashboard_port == 8001


def test_missing_monitoring_yaml_falls_back_to_console_only_defaults(tmp_path):
    """Alerting must never be silently off, so a repo without
    monitoring.yaml still loads with console alerts enabled."""
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    (config_dir / "monitoring.yaml").unlink()
    state_dir = tmp_path / "state"

    config = load_config(config_dir=config_dir, state_dir=state_dir)

    assert config.monitoring.console_alerts is True
    assert config.monitoring.email.enabled is False


def test_email_alerts_enabled_without_a_destination_is_rejected(tmp_path):
    """An alert channel that cannot deliver is worse than one that is
    honestly switched off."""
    config_dir = tmp_path / "config"
    _copy_config_dir("config", config_dir)
    state_dir = tmp_path / "state"

    monitoring_path = config_dir / "monitoring.yaml"
    monitoring_path.write_text(
        "console_alerts: true\n"
        "email:\n"
        "  enabled: true\n"
        "  smtp_host: \"\"\n"
        "  sender: \"\"\n"
        "  recipients: []\n"
    )

    import pytest

    with pytest.raises(Exception, match="recipients"):
        load_config(config_dir=config_dir, state_dir=state_dir)


def test_monitoring_yaml_contains_no_password_field():
    """The SMTP password is read from an environment variable at send
    time; a password field in a committed config file would be a
    credential waiting to be committed."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    text = (repo_root / "config" / "monitoring.yaml").read_text()

    assert "password:" not in text
    assert "password_env_var:" in text
