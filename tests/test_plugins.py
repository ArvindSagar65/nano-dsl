"""Regression tests for the minimal plugin system.

Proves that:
  - discovery registers the DockerPlugin under the plugin registry
  - docker.* commands resolve through the plugin backend path
  - custom plugins (name, probes, handlers) drop in without touching core code
  - a broken/absent plugin layer degrades gracefully to direct backend calls
"""
import pytest

from nano_logic import plugins as registry
from nano_logic.dsl import execute_command
from nano_logic.engine import _METRIC_REGISTRY, fetch_metric_value, register_plugin_metrics
from nano_logic.plugins import docker_probe
from nano_logic.plugins.base import PluginBase
from nano_logic.plugins.docker_plugin import DockerPlugin

# ═══════════════════════════════════════════════
#  Discovery & registration
# ═══════════════════════════════════════════════

class TestDiscovery:
    def test_docker_plugin_is_discovered(self):
        from nano_logic import discover_plugins
        discover_plugins()  # idempotent re-run must not break anything
        plugin = registry.get_plugin("docker")
        assert isinstance(plugin, DockerPlugin)

    def test_discovery_finds_all_docker_command_handlers(self):
        expected = {"docker.ps", "docker.stats", "docker.info", "docker.images",
                    "docker.containers", "docker.logs", "docker.networks",
                    "docker.volumes"}
        assert expected <= set(registry.COMMAND_HANDLERS)

    def test_docker_probe_registered_for_alerts(self):
        assert "docker.containers.running" in registry.METRIC_PROBES

    def test_plugin_metric_reachable_via_engine(self):
        val = fetch_metric_value("docker.containers.running")
        if docker_probe.is_daemon_reachable():
            assert isinstance(val, float) and val >= 0
        else:
            assert val is None  # unavailable -> rule evaluation skips it


# ═══════════════════════════════════════════════
#  DSL resolves through the plugin backend path
# ═══════════════════════════════════════════════

class TestPluginBackendRouting:
    @pytest.mark.parametrize("cmd,key_report", [
        ("docker.info", "docker_info_report"),
        ("docker.images", "docker_images_report"),
        ("docker.containers", "docker_containers_report"),
        ("docker.networks", "docker_networks_report"),
        ("docker.volumes", "docker_volumes_report"),
        ("docker.ps", "docker_ps_report"),
        ("docker.stats", "docker_stats_report"),
    ])
    def test_command_flows_through_plugin_to_backend(self, cmd, key_report, monkeypatch):
        """DSL -> DockerPlugin handler -> docker_probe report function."""
        marker = f"ROUTED::{key_report}"
        monkeypatch.setattr(docker_probe, key_report, lambda: marker)
        assert execute_command(cmd) == marker

    def test_logs_target_passed_through_plugin(self, monkeypatch):
        seen = {}
        def fake_logs(name):
            seen["n"] = name
            return f"logs:{name}"
        monkeypatch.setattr(docker_probe, "docker_logs_report", fake_logs)
        assert execute_command("docker.logs mybox") == "logs:mybox"
        assert seen["n"] == "mybox"

    def test_fallback_when_registry_has_no_handler(self, monkeypatch):
        """Even with an empty plugin registry, commands still resolve."""
        monkeypatch.setattr(_plugin_registry_module(), "COMMAND_HANDLERS", {})
        result = execute_command("docker.info")
        assert isinstance(result, str) and result.strip()


def _plugin_registry_module():
    import nano_logic.plugins
    return nano_logic.plugins


# ═══════════════════════════════════════════════
#  Custom plugins drop in without touching core code
# ═══════════════════════════════════════════════

class DummyProbePlugin(PluginBase):
    name = "dummy_test"
    description = "test-only plugin"

    def __init__(self):
        self.probe_registry = {"dummy.metric": lambda: 42.0}
        self.command_handlers = {"dummy.ping": lambda *c: "pong"}

    def register(self, app=None) -> None:
        pass


@pytest.fixture
def dummy_plugin():
    plugin = DummyProbePlugin()
    yield plugin
    # cleanup so other tests never see the dummy
    registry.PLUGINS.pop(plugin.name, None)
    registry.COMMAND_HANDLERS.pop("dummy.ping", None)
    registry.METRIC_PROBES.pop("dummy.metric", None)
    _METRIC_REGISTRY.pop("dummy.metric", None)


class TestCustomPluginDropIn:
    def test_register_plugin_merges_all_registries(self, dummy_plugin):
        registry.register_plugin(dummy_plugin)
        assert registry.get_plugin("dummy_test") is dummy_plugin
        assert registry.get_command_handler("dummy.ping")() == "pong"
        assert registry.METRIC_PROBES["dummy.metric"]() == 42.0

    def test_custom_probe_feeds_engine_alerts(self, dummy_plugin):
        registry.register_plugin(dummy_plugin)
        register_plugin_metrics()
        assert fetch_metric_value("dummy.metric") == 42.0

    def test_builtin_metrics_keep_priority(self, dummy_plugin):
        from nano_logic.engine import _METRIC_REGISTRY as reg
        builtin_cpu_util = reg["cpu.util"]
        registry.register_plugin(dummy_plugin)
        dummy_plugin.probe_registry["cpu.util"] = lambda: 999.0
        register_plugin_metrics()
        assert reg["cpu.util"] is builtin_cpu_util

    def test_register_error_is_contained(self):
        class Explody(PluginBase):
            name = "explody_test"
            def register(self, app=None):
                raise RuntimeError("boom")

        try:
            registry.register_plugin(Explody())  # must not raise
            assert registry.get_plugin("explody_test") is not None
        finally:
            registry.PLUGINS.pop("explody_test", None)
