"""Central plugin registry.

Discovery (see nano_logic.__init__) hands every instantiated PluginBase
subclass to register_plugin(). This module owns the resulting registries:

  PLUGINS          name -> plugin instance
  COMMAND_HANDLERS "docker.ps" -> callable(*children) -> str
  METRIC_PROBES    metric name -> callable() -> float | None
  ACTION_HANDLERS  alert action name ("slack") -> callable(context) -> bool

The DSL and engine read these registries instead of importing backends
directly, so new plugins drop in without touching core code.
"""
from __future__ import annotations

from typing import Callable

from nano_logic.plugins.base import PluginBase

PLUGINS: dict[str, PluginBase] = {}
COMMAND_HANDLERS: dict[str, Callable] = {}
METRIC_PROBES: dict[str, Callable] = {}
ACTION_HANDLERS: dict[str, Callable] = {}


def register_plugin(plugin: PluginBase) -> None:
    """Merge one plugin instance into the registries. Idempotent by name."""
    PLUGINS[plugin.name] = plugin
    for key, handler in getattr(plugin, "command_handlers", {}).items():
        COMMAND_HANDLERS[key] = handler
    for metric_name, probe in getattr(plugin, "probe_registry", {}).items():
        METRIC_PROBES.setdefault(metric_name, probe)
    for action_name, handler in getattr(plugin, "action_registry", {}).items():
        ACTION_HANDLERS[action_name] = handler
    try:
        plugin.register(None)  # no app object yet; plugins must tolerate None
    except Exception:  # noqa: BLE001 — registration issues are non-fatal
        pass


def get_command_handler(key: str) -> Callable | None:
    """Resolve a dotted command key ("docker.ps") to its handler, or None."""
    return COMMAND_HANDLERS.get(key)


def get_action_handler(name: str) -> Callable | None:
    """Resolve an alert action name ("slack") to its handler, or None.

    Unknown names (like the built-in "log") simply return None — callers
    fall back to their existing behavior.
    """
    return ACTION_HANDLERS.get(name)


def get_plugin(name: str) -> PluginBase | None:
    return PLUGINS.get(name)


def reset_registries() -> None:
    """Test helper — empty all registries."""
    PLUGINS.clear()
    COMMAND_HANDLERS.clear()
    METRIC_PROBES.clear()
    ACTION_HANDLERS.clear()
