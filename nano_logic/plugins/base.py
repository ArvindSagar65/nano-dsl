"""Plugin base module that defines the Plugin contract."""
from typing import TYPE_CHECKING, Callable, Dict, Optional

if TYPE_CHECKING:
    from nano_logic.dashboard import SystemDashboardApp

# Typing alias for readability
ProbeCallable = Callable[..., Optional[float]]

class PluginBase:
    """
    All plugins must subclass this class and implement the required attributes
    and methods. The base class provides a contract for:
      - `name`: Short identifier used in the plugin registry.
      - `probe_registry`: Mapping of metric names to callables returning
        float | None (wired into the engine's metric registry).
      - `commands`: List of Lark grammar fragments to extend the DSL.
      - `command_handlers`: Mapping of dotted command keys ("docker.ps") to
        callables (*children) -> str. The DSL resolves through these before
        any built-in backend.
      - `action_registry`: Mapping of alert action names ("slack") to
        callables (context: dict) -> bool. Fired by the engine when a rule
        whose `action` matches triggers. Must never raise.
      - `transformer_hooks`: Optional hooks to transform parsed Lark nodes.
      - `register(app)`: Called once when the plugin is discovered; `app` may
        be None during early discovery — plugins must tolerate that.
    """
    name: str
    description: str = ""
    probe_registry: Dict[str, ProbeCallable] = {}
    commands: list[str] = []
    command_handlers: Dict[str, Callable[..., str]] = {}
    action_registry: Dict[str, Callable[[dict], bool]] = {}
    transformer_hooks: Dict[str, Callable] = {}

    def register(self, app: "Optional[SystemDashboardApp]" = None) -> None:
        """
        Called by the discovery flow when the plugin is registered.
        Plugins should override this method to:
          - Register their metric probes with the global registry.
          - Add their command fragments to the Lark parser.
          - Optionally register help text or UI elements.
        """
        raise NotImplementedError("Plugins must implement 'register(app)'")
