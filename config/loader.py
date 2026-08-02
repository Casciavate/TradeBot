"""Loads and validates config/*.yaml into an AppConfig, and logs a
timestamped diff whenever risk-relevant sections (risk_limits, account)
change from the last load -- section 2's "changes must be logged with a
timestamp and diff" requirement."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from config.schema import AppConfig
from monitoring.audit_log import AuditLog

CONFIG_DIR = Path(__file__).parent
DEFAULT_STATE_DIR = Path(__file__).parent.parent / "state"

# Sections whose changes get diffed and logged -- these are the ones the
# build spec calls "risk parameters."
_RISK_RELEVANT_SECTIONS = ("risk_limits", "account")


def _read_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _load_raw(config_dir: Path) -> dict[str, Any]:
    return {
        "account": _read_yaml(config_dir / "account.yaml"),
        "risk_limits": _read_yaml(config_dir / "risk_limits.yaml"),
        "universe": _read_yaml(config_dir / "universe.yaml"),
        "strategies": _read_yaml(config_dir / "strategies.yaml"),
        "approval": _read_yaml(config_dir / "approval.yaml"),
        "connection": _read_yaml(config_dir / "connection.yaml"),
    }


def _diff(old: dict, new: dict) -> dict:
    keys = set(old) | set(new)
    changes = {}
    for key in keys:
        if old.get(key) != new.get(key):
            changes[key] = {"old": old.get(key), "new": new.get(key)}
    return changes


def _log_risk_relevant_changes(raw: dict, state_dir: Path) -> None:
    snapshot_path = state_dir / "risk_config.snapshot.json"
    audit = AuditLog(state_dir / "config_audit.log")

    current = {section: raw[section] for section in _RISK_RELEVANT_SECTIONS}
    previous: dict = {}
    if snapshot_path.exists():
        with open(snapshot_path) as f:
            previous = json.load(f)

    for section in _RISK_RELEVANT_SECTIONS:
        changes = _diff(previous.get(section, {}), current[section])
        if changes:
            audit.write(
                "config_change",
                {"section": section, "changes": changes, "first_load": not previous},
            )

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w") as f:
        json.dump(current, f, indent=2, sort_keys=True, default=str)


def load_config(
    config_dir: Path | str = CONFIG_DIR,
    state_dir: Path | str = DEFAULT_STATE_DIR,
    *,
    log_changes: bool = True,
) -> AppConfig:
    config_dir = Path(config_dir)
    state_dir = Path(state_dir)

    raw = _load_raw(config_dir)
    app_config = AppConfig.model_validate(raw)

    if log_changes:
        _log_risk_relevant_changes(raw, state_dir)

    return app_config
