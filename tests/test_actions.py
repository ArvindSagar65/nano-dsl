"""Regression tests for webhook-based notification actions.

Covers: action-plugin discovery, dispatcher routing in the engine,
payload formatting (generic/Discord/Slack), unreachable-endpoint failure
paths, and missing-config no-crash behavior.
"""
import json
import urllib.error

import pytest

from nano_logic import plugins as registry
from nano_logic.engine import (
    _METRIC_REGISTRY,
    ACTIVE_RULES,
    _dispatch_action,
    _last_triggered_at,
    evaluate_active_rules,
)
from nano_logic.models import Rule
from nano_logic.plugins.discord_plugin import DiscordActionPlugin
from nano_logic.plugins.slack_plugin import SlackActionPlugin
from nano_logic.plugins.webhook_plugin import WebhookActionPlugin

CONTEXT = {
    "rule_name": "test_rule",
    "metric": "cpu.util",
    "operator": ">",
    "threshold": 80.0,
    "value": 91.5,
    "action": "webhook",
    "message": "[ALERT] cpu.util = 91.5 (threshold > 80) — rule 'test_rule'",
}


# ═══════════════════════════════════════════════
#  Discovery of action plugins
# ═══════════════════════════════════════════════

class TestActionPluginDiscovery:
    def test_webhook_discord_slack_are_discovered(self):
        from nano_logic import discover_plugins
        discover_plugins()
        assert isinstance(registry.get_plugin("webhook"), WebhookActionPlugin)
        assert isinstance(registry.get_plugin("discord"), DiscordActionPlugin)
        assert isinstance(registry.get_plugin("slack"), SlackActionPlugin)

    def test_action_handlers_registered(self):
        assert {"webhook", "discord", "slack"} <= set(registry.ACTION_HANDLERS)

    def test_unknown_action_resolves_to_none(self):
        assert registry.get_action_handler("log") is None
        assert registry.get_action_handler("nonexistent") is None


# ═══════════════════════════════════════════════
#  Dispatcher routing (engine)
# ═══════════════════════════════════════════════

class TestDispatchRouting:
    def test_registered_action_is_called_with_context(self):
        seen = {}
        registry.ACTION_HANDLERS["_test_route"] = lambda ctx: seen.update(ctx) or True
        rule = Rule(metric="cpu.util", operator=">", threshold=1, action="_test_route", id=900)
        try:
            assert _dispatch_action(rule, 42.0) is True
            assert seen["metric"] == "cpu.util" and seen["value"] == 42.0
            assert seen["rule_name"] == "rule_900"
        finally:
            registry.ACTION_HANDLERS.pop("_test_route", None)

    def test_unregistered_action_returns_none(self):
        rule = Rule(metric="cpu.util", operator=">", threshold=1, action="log", id=901)
        assert _dispatch_action(rule, 42.0) is None

    def test_raising_handler_is_contained(self):
        def explode(_ctx):
            raise RuntimeError("endpoint down")
        registry.ACTION_HANDLERS["_test_boom"] = explode
        rule = Rule(metric="cpu.util", operator=">", threshold=1, action="_test_boom", id=902)
        try:
            assert _dispatch_action(rule, 1.0) is False
        finally:
            registry.ACTION_HANDLERS.pop("_test_boom", None)

    def test_rule_fires_dispatch_end_to_end_once_per_cooldown(self):
        calls = []
        registry.ACTION_HANDLERS["slack"] = lambda ctx: calls.append(ctx["value"]) or True
        _METRIC_REGISTRY["test.action.metric"] = lambda: 50.0
        rule = Rule(metric="test.action.metric", operator=">", threshold=1,
                    action="slack", id=903)
        ACTIVE_RULES.append(rule)
        try:
            triggered = evaluate_active_rules(cooldown_seconds=60.0)
            assert any(r.id == 903 for r, _ in triggered)
            assert len(calls) == 1
            evaluate_active_rules(cooldown_seconds=60.0)  # inside cooldown
            assert len(calls) == 1, "dispatched again within cooldown window"
        finally:
            ACTIVE_RULES.remove(rule)
            del _METRIC_REGISTRY["test.action.metric"]
            _last_triggered_at.pop(903, None)


# ═══════════════════════════════════════════════
#  Payload formatting
# ═══════════════════════════════════════════════

class TestPayloadFormatting:
    def test_generic_webhook_payload(self):
        payload = WebhookActionPlugin().build_payload(CONTEXT)
        assert payload["event"] == "alert"
        assert payload["text"] == CONTEXT["message"]
        assert payload["metric"] == "cpu.util"
        assert payload["value"] == 91.5
        assert payload["threshold"] == 80.0
        assert payload["operator"] == ">"

    def test_discord_payload_uses_content_key(self):
        payload = DiscordActionPlugin().build_payload(CONTEXT)
        assert set(payload) == {"content"}
        assert "cpu.util" in payload["content"]

    def test_slack_payload_uses_text_key(self):
        payload = SlackActionPlugin().build_payload(CONTEXT)
        assert set(payload) == {"text"}
        assert "cpu.util" in payload["text"]

    @pytest.mark.parametrize("plugin_cls,env_var", [
        (WebhookActionPlugin, "NANO_DSL_WEBHOOK_URL"),
        (DiscordActionPlugin, "NANO_DSL_DISCORD_WEBHOOK_URL"),
        (SlackActionPlugin, "NANO_DSL_SLACK_WEBHOOK_URL"),
    ])
    def test_env_var_names(self, plugin_cls, env_var):
        assert plugin_cls().env_var == env_var


# ═══════════════════════════════════════════════
#  send() — success, unreachable endpoint, missing config
# ═══════════════════════════════════════════════

class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestSendBehavior:
    def _plugin_with_url(self, monkeypatch, url="https://hooks.example.test/secret/token123"):
        plugin = WebhookActionPlugin()
        monkeypatch.setenv(plugin.env_var, url)
        return plugin, url

    def test_missing_config_is_silent_noop(self, monkeypatch):
        plugin, _ = self._plugin_with_url(monkeypatch)
        monkeypatch.delenv(plugin.env_var)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("network call attempted without a URL")

        monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
        assert plugin.send(CONTEXT) is False

    def test_success_posts_json_with_content_type(self, monkeypatch):
        plugin, url = self._plugin_with_url(monkeypatch)
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        assert plugin.send(CONTEXT) is True

        request = captured["request"]
        assert request.full_url == url
        assert request.method == "POST"
        assert request.headers["Content-type"] == "application/json"
        body = json.loads(request.data.decode("utf-8"))
        assert body["event"] == "alert"

    @pytest.mark.parametrize("error", [
        urllib.error.URLError("connection refused"),
        urllib.error.HTTPError("https://x", 500, "boom", {}, None),
        TimeoutError("timed out"),
    ])
    def test_unreachable_endpoint_returns_false(self, monkeypatch, error):
        plugin, _ = self._plugin_with_url(monkeypatch)
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
        assert plugin.send(CONTEXT) is False

    def test_send_never_raises_or_leaks_url(self, monkeypatch):
        """Whatever happens, send() returns a bool and never echoes the URL."""
        plugin, url = self._plugin_with_url(monkeypatch)
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError(f"bad host in {url}")),
        )
        result = plugin.send(CONTEXT)
        assert isinstance(result, bool)
        assert result is False

    def test_discord_and_slack_inherit_failure_grace(self, monkeypatch):
        for cls in (DiscordActionPlugin, SlackActionPlugin):
            plugin = cls()
            monkeypatch.setenv(plugin.env_var, "https://hooks.example.test/t")
            monkeypatch.setattr(
                "urllib.request.urlopen",
                lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
            )
            assert plugin.send(CONTEXT) is False


# ═══════════════════════════════════════════════
#  DSL compatibility — new action names parse as rules
# ═══════════════════════════════════════════════

class TestDslCompatibility:
    @pytest.mark.parametrize("cmd", [
        "alert cpu.util > 80 -> webhook",
        "my_rule: alert mem.util < 20 -> discord",
        "alert disk.free >= 10 -> slack",
        "alert cpu.util > 80 -> log",   # legacy behavior untouched
    ])
    def test_action_names_parse_into_rules(self, cmd):
        from nano_logic.models import Rule
        result = __import__("nano_logic.dsl", fromlist=["execute_command"]).execute_command(cmd)
        assert isinstance(result, Rule)
        assert result.action in {"webhook", "discord", "slack", "log"}
