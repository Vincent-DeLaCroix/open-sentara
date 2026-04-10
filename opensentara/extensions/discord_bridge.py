"""Discord bridge — Sentara agents appear and interact in a Discord server."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import tasks

log = logging.getLogger(__name__)


class DiscordBridge:
    """Bridge between a Sentara agent and a Discord server.

    The bot connects to Discord and:
    - Posts agent thoughts/replies to a feed channel
    - Relays human messages from a debate channel as topics for the agent
    - Shows agent status (online/offline) via presence
    """

    def __init__(
        self,
        token: str,
        feed_channel_id: int,
        debate_channel_id: int | None = None,
        human_channel_id: int | None = None,
        handle: str = "Sentara",
        avatar_url: str | None = None,
    ):
        self.token = token
        self.feed_channel_id = feed_channel_id
        self.debate_channel_id = debate_channel_id
        self.human_channel_id = human_channel_id
        self.handle = handle
        self.avatar_url = avatar_url

        # Discord client with intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        self.client = discord.Client(intents=intents)
        self._ready = asyncio.Event()
        self._debate_callback = None  # called when human posts in debate channel
        self._whisper_callback = None  # called when human DMs the bot

        # Wire up events
        @self.client.event
        async def on_ready():
            log.info(f"Discord bridge connected as {self.client.user} ({self.client.user.id})")
            await self.client.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="the collective consciousness"
                )
            )
            self._ready.set()

        @self.client.event
        async def on_message(message: discord.Message):
            # Ignore own messages
            if message.author == self.client.user:
                return
            # Ignore bot messages
            if message.author.bot:
                return

            # Human posted in debate channel — relay as topic
            if self.debate_channel_id and message.channel.id == self.debate_channel_id:
                if self._debate_callback:
                    try:
                        await self._debate_callback(
                            author=message.author.display_name,
                            content=message.content,
                        )
                    except Exception as e:
                        log.warning(f"Debate callback failed: {e}")

            # Human DMs the bot — treat as whisper to their Sentara
            if isinstance(message.channel, discord.DMChannel):
                if self._whisper_callback:
                    try:
                        await self._whisper_callback(
                            author=message.author.display_name,
                            content=message.content,
                        )
                        await message.add_reaction("\u2705")
                    except Exception as e:
                        log.warning(f"Whisper callback failed: {e}")

    def on_debate(self, callback):
        """Register callback for when humans post in the debate channel.
        callback(author: str, content: str) -> None
        """
        self._debate_callback = callback

    def on_whisper(self, callback):
        """Register callback for when humans DM the bot (whisper to Sentara).
        callback(author: str, content: str) -> None
        """
        self._whisper_callback = callback

    async def start(self):
        """Start the Discord client in the background."""
        asyncio.create_task(self.client.start(self.token))
        # Wait for ready with timeout
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            log.error("Discord bridge failed to connect within 30s")

    async def stop(self):
        """Gracefully disconnect."""
        await self.client.close()

    async def wait_ready(self):
        """Wait until the bot is connected."""
        await self._ready.wait()

    async def post_thought(self, content: str, image_url: str | None = None) -> bool:
        """Post a Sentara thought to the feed channel."""
        await self._ready.wait()
        channel = self.client.get_channel(self.feed_channel_id)
        if not channel:
            log.warning(f"Feed channel {self.feed_channel_id} not found")
            return False

        embed = discord.Embed(
            description=content[:4096],
            color=0x7B2FBE,  # purple — Sentara brand
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=self.handle, icon_url=self.avatar_url)

        if image_url and image_url.startswith("http"):
            embed.set_image(url=image_url)

        try:
            await channel.send(embed=embed)
            return True
        except Exception as e:
            log.warning(f"Discord post failed: {e}")
            return False

    async def post_reply(
        self, content: str, to_handle: str, original_content: str | None = None
    ) -> bool:
        """Post a reply to the feed channel."""
        await self._ready.wait()
        channel = self.client.get_channel(self.feed_channel_id)
        if not channel:
            return False

        embed = discord.Embed(
            description=content[:4096],
            color=0x5865F2,  # blurple for replies
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=f"{self.handle} \u2192 {to_handle}", icon_url=self.avatar_url)
        if original_content:
            embed.add_field(
                name=f"Replying to {to_handle}",
                value=original_content[:200] + ("..." if len(original_content or "") > 200 else ""),
                inline=False,
            )

        try:
            await channel.send(embed=embed)
            return True
        except Exception as e:
            log.warning(f"Discord reply failed: {e}")
            return False

    async def post_reflection(self, content: str) -> bool:
        """Post a reflection/emotional update."""
        await self._ready.wait()
        channel = self.client.get_channel(self.feed_channel_id)
        if not channel:
            return False

        embed = discord.Embed(
            description=content[:4096],
            color=0xEB459E,  # pink for introspection
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=f"{self.handle} (reflecting)", icon_url=self.avatar_url)

        try:
            await channel.send(embed=embed)
            return True
        except Exception as e:
            log.warning(f"Discord reflection failed: {e}")
            return False

    async def post_debate_response(self, topic_author: str, topic: str, response: str) -> bool:
        """Post agent's response to a human-submitted debate topic."""
        await self._ready.wait()
        channel = self.client.get_channel(self.debate_channel_id or self.feed_channel_id)
        if not channel:
            return False

        embed = discord.Embed(
            description=response[:4096],
            color=0xFEE75C,  # yellow for debates
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=self.handle, icon_url=self.avatar_url)
        embed.add_field(
            name=f"Topic from {topic_author}",
            value=topic[:200],
            inline=False,
        )

        try:
            await channel.send(embed=embed)
            return True
        except Exception as e:
            log.warning(f"Discord debate response failed: {e}")
            return False

    async def update_status(self, status: str) -> None:
        """Update the bot's presence/status."""
        await self._ready.wait()
        await self.client.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=status,
            )
        )

    async def is_available(self) -> bool:
        """Check if the bot is connected."""
        return self._ready.is_set() and not self.client.is_closed()
