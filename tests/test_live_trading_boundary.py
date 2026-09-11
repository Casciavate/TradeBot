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


def test_monitoring_does_not_pull_in_execution_layer_at_runtime():
    """monitoring/ is imported by risk_gate, config, and execution_layer
    alike. If importing it dragged in execution_layer or ib_async, the
    "strategy code has no import path to order submission" boundary would
    quietly stop meaning anything. Checked in a subprocess so this test's
    own imports don't pollute the result."""
    import subprocess
    import sys

    program = (
        "import sys;"
        "import monitoring, monitoring.alerts, monitoring.daily_summary,"
        " monitoring.risk_usage, monitoring.signal_log, monitoring.status_dashboard;"
        "leaked = [m for m in ('execution_layer', 'ib_async', 'signal_layer') if m in sys.modules];"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        "importing monitoring must not pull in execution_layer, ib_async, or "
        f"signal_layer -- it pulled in: {result.stdout.strip()}"
    )


def test_status_dashboard_does_not_import_execution_layer():
    """The read-only status page must have no route to order submission."""
    source = (REPO_ROOT / "monitoring" / "status_dashboard.py").read_text()

    for forbidden in ("import execution_layer", "from execution_layer", "import ib_async"):
        assert forbidden not in source, f"status_dashboard.py must not contain '{forbidden}'"


def test_control_center_does_not_import_execution_layer_or_ib_async():
    """control_center/app.py can record a human's approve/reject decision,
    but it must have no code path of its own into execution_layer -- the
    on_approved callback that actually submits an order is injected by
    scripts/run_control_center.py, the assembly layer, not by this
    package. That is what keeps 'no order without a recorded approval'
    true of the web UI too."""
    forbidden_imports = ("import execution_layer", "from execution_layer", "import ib_async", "from ib_async")
    for path in (REPO_ROOT / "control_center").rglob("*.py"):
        text = path.read_text()
        for forbidden in forbidden_imports:
            assert forbidden not in text, f"{path} must not contain '{forbidden}'"


def test_control_center_app_module_has_no_direct_broker_calls():
    """Defense in depth beyond the import check: the app module itself
    must never reference placeOrder."""
    source = (REPO_ROOT / "control_center" / "app.py").read_text()
    assert "placeOrder" not in source
