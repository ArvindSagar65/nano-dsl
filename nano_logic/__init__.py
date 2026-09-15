"""Nano Logic terminal dashboard package."""
# Auto-discover plugins on package import
import importlib
import pkgutil

from .plugins.base import PluginBase


def discover_plugins() -> list[PluginBase]:
    """Import every module in the plugins subpackage and register any
    PluginBase subclass they define.

    Convention: a plugin module either exposes a single class named
    ``Plugin``, or contains exactly one PluginBase subclass. Each discovered
    class is instantiated once and handed to the central registry. A broken
    plugin module is skipped, never allowed to break the app.
    """
    from . import plugins

    registered: list[PluginBase] = []
    for _, mod_name, _ in pkgutil.iter_modules(plugins.__path__):
        if mod_name.startswith("_") or mod_name == "base":
            continue
        try:
            module = importlib.import_module(f"{plugins.__name__}.{mod_name}")
            candidates = [
                obj for obj in vars(module).values()
                if isinstance(obj, type)
                and issubclass(obj, PluginBase)
                and obj is not PluginBase
                and getattr(obj, "__module__", "") == module.__name__
            ]
            plugin_cls = getattr(module, "Plugin", None)
            if plugin_cls is not None:
                candidates = [plugin_cls]
            for plugin_cls in candidates:
                plugin = plugin_cls()
                plugins.register_plugin(plugin)
                registered.append(plugin)
        except Exception:  # noqa: BLE001 — a bad plugin must not kill the app
            continue
    return registered


discover_plugins()
