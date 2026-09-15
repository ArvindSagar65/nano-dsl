"""Discord webhook notification action.

Payload shape per Discord webhook API: {"content": "<message>"}.
Webhook URL comes from $NANO_DSL_DISCORD_WEBHOOK_URL.
"""
from __future__ import annotations

from nano_logic.plugins.webhook_plugin import WebhookActionPlugin


class DiscordActionPlugin(WebhookActionPlugin):
    name = "discord"
    description = "Discord webhook notification action"
    action_key = "discord"
    env_var = "NANO_DSL_DISCORD_WEBHOOK_URL"

    def build_payload(self, context: dict) -> dict:
        return {"content": self.build_message(context)}


Plugin = DiscordActionPlugin
