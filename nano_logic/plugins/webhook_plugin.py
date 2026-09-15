"""Generic webhook action plugin.

Sends an HTTP POST with a JSON payload when a triggered alert rule names
this action. Concrete Discord/Slack plugins subclass this and only override
the payload shape and their environment variable name.

Safety properties:
  - Webhook URLs come from the environment at send time (never hard-coded,
    never logged). A missing URL is a silent no-op returning False.
  - All network failures degrade to False — alerting never crashes.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from nano_logic.plugins.base import PluginBase

_POST_TIMEOUT = 5  # seconds


class WebhookActionPlugin(PluginBase):
    """Base for POST-JSON webhook notifiers. Subclasses set `name`,
    `action_key`, `env_var` and override `build_payload()`."""

    name = "webhook"
    description = "Generic JSON webhook notification action"
    action_key = "webhook"
    env_var = "NANO_DSL_WEBHOOK_URL"

    def __init__(self) -> None:
        self.action_registry = {self.action_key: self.send}

    def register(self, app=None) -> None:
        """No app-level UI registration needed."""

    def build_message(self, context: dict) -> str:
        return str(context.get("message", ""))

    def build_payload(self, context: dict) -> dict:
        """Default generic payload; Discord/Slack override this."""
        return {
            "event": "alert",
            "text": self.build_message(context),
            "rule": context.get("rule_name"),
            "metric": context.get("metric"),
            "value": context.get("value"),
            "threshold": context.get("threshold"),
            "operator": context.get("operator"),
        }

    def get_webhook_url(self) -> str | None:
        url = os.environ.get(self.env_var, "").strip()
        return url or None

    def send(self, context: dict) -> bool:
        """POST the payload. Returns True on 2xx, False otherwise."""
        url = self.get_webhook_url()
        if url is None:
            return False
        try:
            body = json.dumps(self.build_payload(context)).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=_POST_TIMEOUT):
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            # Never include the URL in any output: it embeds a secret token.
            return False

# Discovery convention: expose the plugin class as `Plugin`.
Plugin = WebhookActionPlugin
