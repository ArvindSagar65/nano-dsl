"""Slack webhook notification action.

Payload shape per Slack incoming-webhook API: {"text": "<message>"}.
Webhook URL comes from $NANO_DSL_SLACK_WEBHOOK_URL.
"""
from __future__ import annotations

from nano_logic.plugins.webhook_plugin import WebhookActionPlugin


class SlackActionPlugin(WebhookActionPlugin):
    name = "slack"
    description = "Slack webhook notification action"
    action_key = "slack"
    env_var = "NANO_DSL_SLACK_WEBHOOK_URL"

    def build_payload(self, context: dict) -> dict:
        return {"text": self.build_message(context)}


Plugin = SlackActionPlugin
