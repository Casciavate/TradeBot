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
