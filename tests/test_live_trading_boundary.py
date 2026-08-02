"""Section 0, rule 1: LIVE_TRADING must be impossible to set via any code
path the strategy layer touches. This test enforces that structurally by
scanning the whole repo for the string and failing if it shows up anywhere
outside the small set of files allowed to know about it."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

ALLOWED_PATH_PREFIXES = ("execution_layer/", "docs/", "tests/", "scripts/")
ALLOWED_EXACT_FILES = ("config/connection.yaml",)

EXCLUDED_DIR_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", "state", "node_modules"}
SEARCHED_SUFFIXES = {".py", ".yaml", ".yml", ".md"}


def _iter_repo_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SEARCHED_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        yield path


def test_live_trading_string_only_appears_in_allowed_files():
    offending = []
    for path in _iter_repo_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(ALLOWED_PATH_PREFIXES) or relative in ALLOWED_EXACT_FILES:
            continue
        if "LIVE_TRADING" in path.read_text(errors="ignore"):
            offending.append(relative)

    assert offending == [], (
        "LIVE_TRADING must only be referenced in execution_layer/, docs/, tests/, "
        f"scripts/, or config/connection.yaml -- found it in: {offending}"
    )


def test_signal_layer_and_risk_gate_do_not_import_execution_layer():
    forbidden_imports = ("import execution_layer", "from execution_layer", "import ib_async", "from ib_async")
    for package in ("signal_layer", "risk_gate"):
        for path in (REPO_ROOT / package).rglob("*.py"):
            text = path.read_text()
            for forbidden in forbidden_imports:
                assert forbidden not in text, f"{path} must not contain '{forbidden}'"
