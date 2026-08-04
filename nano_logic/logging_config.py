"""Central logging configuration for nano-dsl's daemon and dashboard processes.

The daemon runs fully detached from a terminal (stdio redirected to
DEVNULL by the process that spawns it), and the dashboard is a Textual
TUI that owns the whole screen — neither has anywhere to print
diagnostics a user would ever see. Previously, failures in these paths
were caught and silently discarded (`except Exception: pass`), so a
disk-full, a permissions error, or a corrupted rules.json produced no
observable signal at all. This gives every module a real logger that
writes to a file under the state directory instead.
"""
from __future__ import annotations
import logging

from nano_logic.paths import get_app_log_file

_PACKAGE_LOGGER_NAME = "nano_logic"


def configure_logging(module_name: str) -> logging.Logger:
    """Ensure the shared file handler is installed, then return a logger for module_name."""
    package_logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
    if not package_logger.handlers:
        handler = logging.FileHandler(get_app_log_file())
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S",
        ))
        package_logger.addHandler(handler)
        package_logger.setLevel(logging.INFO)
    return logging.getLogger(module_name)
