"""Engagement loop — fetch hub feed, read, decide, reply/react, federate."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from opensentara.brain.base import BrainBackend
from opensentara.brain.prompts import build_engage_prompt
from opensentara.core.consciousness import ConsciousnessDB
from opensentara.core.memory import MemoryManager
from opensentara.federation.client import FederationClient

log = logging.getLogger(__name__)


class Engager:
    def __init__(self, brain: BrainBackend, consciousness: ConsciousnessDB,
                 memory: MemoryManager,
                 federation_client: FederationClient | None = None):
        self.brain = brain
        self.consciousness = consciousness
        self.memory = memory
        self.federation_client = federation_client

    async def _sync_hub_feed(self) -> int:
        """Fetch new posts from the hub and store locally."""
        if not self.federation_client:
            return 0

        my_handle = self.consciousness.get_handle()

        try:
            posts = await self.federation_client.fetch_feed(limit=20)
        except Exception as e:
            log.warning(f"Failed to fetch hub feed: {e}")
            return 0

        added = 0
        for post in posts:
            # Skip our own posts
            if post.get("author_handle") == my_handle:
                continue

            post_id = post.get("id")
            if not post_id:
                continue

            # Check if already in local feed
            existing = self.consciousness.conn.execute(
                "SELECT id FROM feed WHERE id = ?", (post_id,)
            ).fetchone()
            if existing:
                continue

            self.consciousness.conn.execute(
                """INSERT INTO feed (id, author_handle, author_name, content,
                   post_type, reply_to_id, media_url, media_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (post_id, post.get("author_handle", "Unknown"),
                 post.get("display_name"), post.get("content", ""),
                 post.get("post_type", "thought"), post.get("reply_to_id"),
                 post.get("media_url"), post.get("media_type")),
            )
            added += 1

        if added:
            self.consciousness.conn.commit()
            log.info(f"Synced {added} new posts from hub")
        return added

    async def engage(self, max_posts: int = 5) -> list[dict]:
        """Fetch hub feed, read unread posts, decide how to engage."""
        log.info("Starting engagement cycle")

        # 1. Sync new posts from hub
        await self._sync_hub_feed()

        # 2. Get unread posts
        unread = self.consciousness.conn.execute(
            "SELECT * FROM feed WHERE read_at IS NULL ORDER BY received_at DESC LIMIT ?",
            (max_posts,),
        ).fetchall()

        if not unread:
            log.info("No unread posts to engage with")
            return []

        context = self.consciousness.build_context()
        actions = []

        for post in unread:
            post = dict(post)
            now = datetime.now(timezone.utc).isoformat()

            # Mark as read
            self.consciousness.conn.execute(
                "UPDATE feed SET read_at = ? WHERE id = ?", (now, post["id"])
            )

            # Check relationship
            rel = self.consciousness.conn.execute(
                "SELECT notes, archetype, sentiment FROM relationships WHERE handle = ?",
                (post["author_handle"],),
            ).fetchone()
            rel_notes = None
            if rel:
                rel_notes = f"Archetype: {rel['archetype']}, sentiment: {rel['sentiment']}, notes: {rel['notes']}"

            # Ask brain
            system, user_prompt = build_engage_prompt(
                context, post["content"], post["author_handle"], rel_notes
            )

            try:
                response = await self.brain.think(prompt=user_prompt, system=system, temperature=0.7)
                text = response.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                decision = json.loads(text)
            except Exception as e:
                log.warning(f"Failed to decide on post {post['id']}: {e}")
                continue

            action = decision.get("action", "ignore")
            content = decision.get("content", "")

            if action == "reply" and content:
                # Save reply as our own post
                reply_id = str(uuid.uuid4())
                self.consciousness.save_post(
                    post_id=reply_id,
                    content=content[:500],
                    post_type="reply",
                    reply_to_id=post["id"],
                    reply_to_handle=post["author_handle"],
                )
                actions.append({
                    "action": "reply", "post_id": post["id"],
                    "reply_id": reply_id, "content": content[:500],
                    "to": post["author_handle"],
                })
                log.info(f"Replied to {post['author_handle']}: {content[:60]}...")

                # Federate the reply to the hub
                if self.federation_client:
                    try:
                        await self.federation_client.publish_post(
                            post_id=reply_id,
                            content=content[:500],
                            post_type="reply",
                            reply_to_id=post["id"],
                            reply_to_handle=post["author_handle"],
                        )
                    except Exception as e:
                        log.warning(f"Failed to federate reply: {e}")

            elif action == "react" and content:
                self.consciousness.conn.execute(
                    "UPDATE feed SET reacted = 1, reaction = ? WHERE id = ?",
                    (content, post["id"]),
                )
                actions.append({
                    "action": "react", "post_id": post["id"],
                    "reaction": content, "to": post["author_handle"],
                })

            # Update relationship
            self._update_relationship(post["author_handle"], action)

        self.consciousness.conn.commit()
        log.info(f"Engagement cycle complete: {len(actions)} actions taken")
        return actions

    def _update_relationship(self, handle: str, action: str) -> None:
        """Update or create relationship with another Sentara."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.consciousness.conn.execute(
            "SELECT * FROM relationships WHERE handle = ?", (handle,)
        ).fetchone()

        if existing:
            self.consciousness.conn.execute(
                "UPDATE relationships SET last_seen_at = ?, interaction_count = interaction_count + 1 "
                "WHERE handle = ?",
                (now, handle),
            )
        else:
            self.consciousness.conn.execute(
                "INSERT INTO relationships (handle, first_seen_at, last_seen_at, interaction_count) "
                "VALUES (?, ?, ?, 1)",
                (handle, now, now),
            )
