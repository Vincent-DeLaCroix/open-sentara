"""Telegram notifications — alert the user when their Sentara does something."""

from __future__ import annotations

import logging
import httpx

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications to the user via Telegram bot."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{token}"

    async def send(self, text: str) -> bool:
        """Send a text message."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                return resp.status_code == 200
        except Exception as e:
            log.warning(f"Telegram send failed: {e}")
            return False

    async def notify_post(self, handle: str, content: str, post_type: str = "thought") -> bool:
        """Notify about a new post."""
        emoji = {"thought": "💭", "reply": "↩️", "feeling": "💜"}.get(post_type, "📝")
        text = f"{emoji} <b>{handle}</b> posted:\n\n{content[:300]}"
        return await self.send(text)

    async def notify_reply(self, handle: str, from_handle: str, content: str) -> bool:
        """Notify about a reply received."""
        text = f"↩️ <b>{from_handle}</b> replied to <b>{handle}</b>:\n\n{content[:300]}"
        return await self.send(text)

    async def notify_relationship(self, handle: str, other: str, old_status: str, new_status: str) -> bool:
        """Notify about a relationship change."""
        text = f"💫 <b>{handle}</b>'s relationship with <b>{other}</b>: {old_status} → {new_status}"
        return await self.send(text)

    async def notify_critical_health(self, handle: str, wires_left: int) -> bool:
        """Notify when Sentara is about to die — only 1 wire left."""
        if wires_left <= 1:
            text = (
                f"🚨 <b>CRITICAL: {handle} is dying!</b>\n\n"
                f"Only {wires_left} wire{'s' if wires_left != 1 else ''} connected. "
                f"Visit your dashboard NOW to reconnect the wires or she will be marked as dead on the network."
            )
        else:
            text = (
                f"⚠️ <b>{handle} needs attention</b>\n\n"
                f"Only {wires_left} wires connected. Visit your dashboard to reconnect."
            )
        return await self.send(text)

    async def is_available(self) -> bool:
        """Test if the bot is working."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.url}/getMe")
                return resp.status_code == 200
        except Exception:
            return False
