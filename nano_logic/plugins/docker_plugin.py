"""Docker plugin — thin discovered-plugin shell over docker_probe.

All real logic lives in docker_probe.py (SDK-first, CLI fallback, graceful
failures). This module only adapts it to the PluginBase contract so the DSL
resolves docker.* commands through the plugin registry.
"""
from __future__ import annotations

from nano_logic.plugins import docker_probe
from nano_logic.plugins.base import PluginBase


def _running_container_count() -> float | None:
    """Scalar probe for alert rules; None signals 'unavailable'."""
    rows = docker_probe.get_containers()
    return float(len(rows)) if isinstance(rows, list) else None


class DockerPlugin(PluginBase):
    name = "docker"
    description = "Read-only Docker introspection via SDK or docker CLI"

    def __init__(self) -> None:
        # Handlers call through the module object, keeping late binding
        # intact (tests can monkeypatch docker_probe functions).
        self.command_handlers = {
            "docker.ps": lambda *c: docker_probe.docker_ps_report(),
            "docker.stats": lambda *c: docker_probe.docker_stats_report(),
            "docker.info": lambda *c: docker_probe.docker_info_report(),
            "docker.images": lambda *c: docker_probe.docker_images_report(),
            "docker.containers": lambda *c: docker_probe.docker_containers_report(),
            "docker.logs": self._logs,
            "docker.networks": lambda *c: docker_probe.docker_networks_report(),
            "docker.volumes": lambda *c: docker_probe.docker_volumes_report(),
        }
        self.probe_registry = {
            "docker.containers.running": _running_container_count,
        }
        self.commands = []  # grammar literals already exist in the core DSL
        self.transformer_hooks = {}

    @staticmethod
    def _logs(*children) -> str:
        name = str(children[0]) if children else ""
        return docker_probe.docker_logs_report(name)

    def register(self, app=None) -> None:
        """No app-level UI registration needed — DSL routing is enough."""
