"""Puts the repo root on sys.path.

Running `python scripts/foo.py` puts `scripts/` on sys.path, not the repo
root, so every `from risk_gate import ...` in these entry points would
fail. Importing this module first fixes that without requiring the package
to be pip-installed or PYTHONPATH to be set by hand.

Every script under scripts/ should start with:

    import _bootstrap  # noqa: F401 -- must precede repo imports
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
