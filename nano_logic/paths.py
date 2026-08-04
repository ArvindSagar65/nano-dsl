"""Filesystem locations for nano-dsl's persistent state.

Resolves an XDG-style state directory instead of relying on each
process's current working directory, so the dashboard and the
independently-launched daemon agree on where rules.json and rule log
files live regardless of where either was started from.
"""
from __future__ import annotations
import os
from pathlib import Path


def get_state_dir() -> Path:
    """Return the directory nano-dsl stores persistent state in, creating it if needed.

    Honors $NANO_DSL_STATE_DIR as an explicit override (used by tests to
    avoid touching real user state); otherwise follows the XDG Base
    Directory spec via $XDG_STATE_HOME, defaulting to ~/.local/state.
    """
    override = os.environ.get("NANO_DSL_STATE_DIR")
    if override:
        state_dir = Path(override)
    else:
        xdg_state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        state_dir = Path(xdg_state_home) / "nano-dsl"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_rules_file() -> Path:
    """Return the path to the persisted rules file."""
    return get_state_dir() / "rules.json"


def get_logs_dir() -> Path:
    """Return the directory rule alert logs are written to, creating it if needed."""
    logs_dir = get_state_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_app_log_file() -> Path:
    """Return the path to nano-dsl's own diagnostic log (separate from per-rule alert logs)."""
    return get_state_dir() / "nano-dsl.log"
