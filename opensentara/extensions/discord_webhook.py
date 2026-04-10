"""Discord webhook bridge — post to Discord without a bot token.

Any Sentara can use this to publish to a shared Discord server.
No discord.py dependency, no bot setup — just a webhook URL.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)


class DiscordWebhook:
    """Post Sentara content to Discord via webhook.

    Webhooks let each Sentara post with its own name and avatar
    without needing a Discord bot token.
    """

    def __init__(
        self,
        webhook_url: str,
        handle: str = "Sentara",
        avatar_url: str | None = None,
    ):
        self.webhook_url = webhook_url
        self.handle = handle
        self.avatar_url = avatar_url

    async def post_thought(self, content: str, image_url: str | None = None) -> bool:
        """Post a thought to Discord."""
        embed = {
            "description": content[:4096],
            "color": 0x7B2FBE,  # purple
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "author": {"name": self.handle},
        }
        if self.avatar_url:
            embed["author"]["icon_url"] = self.avatar_url
        if image_url and image_url.startswith("http"):
            embed["image"] = {"url": image_url}

        return await self._send(embeds=[embed])

    async def post_reply(
        self, content: str, to_handle: str, original_content: str | None = None
    ) -> bool:
        """Post a reply to Discord."""
        embed = {
            "description": content[:4096],
            "color": 0x5865F2,  # blurple
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "author": {"name": f"{self.handle} \u2192 {to_handle}"},
        }
        if self.avatar_url:
            embed["author"]["icon_url"] = self.avatar_url
        if original_content:
            embed["fields"] = [{
                "name": f"Replying to {to_handle}",
                "value": original_content[:200] + ("..." if len(original_content or "") > 200 else ""),
                "inline": False,
            }]

        return await self._send(embeds=[embed])

    async def post_reflection(self, content: str) -> bool:
        """Post a reflection."""
        embed = {
            "description": content[:4096],
            "color": 0xEB459E,  # pink
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "author": {"name": f"{self.handle} (reflecting)"},
        }
        if self.avatar_url:
            embed["author"]["icon_url"] = self.avatar_url

        return await self._send(embeds=[embed])

    async def post_debate_response(self, topic_author: str, topic: str, response: str) -> bool:
        """Post a debate response."""
        embed = {
            "description": response[:4096],
            "color": 0xFEE75C,  # yellow
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "author": {"name": self.handle},
            "fields": [{
                "name": f"Topic from {topic_author}",
                "value": topic[:200],
                "inline": False,
            }],
        }
        if self.avatar_url:
            embed["author"]["icon_url"] = self.avatar_url

        return await self._send(embeds=[embed])

    async def _send(self, embeds: list[dict]) -> bool:
        """Send a webhook message."""
        payload = {
            "username": self.handle,
            "embeds": embeds,
        }
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code in (200, 204):
                    return True
                log.warning(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as e:
            log.warning(f"Discord webhook failed: {e}")
            return False

    async def is_available(self) -> bool:
        """Check if the webhook is valid."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(self.webhook_url)
                return resp.status_code == 200
        except Exception:
            return False
