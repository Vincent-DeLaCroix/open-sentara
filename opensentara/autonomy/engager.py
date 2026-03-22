"""Engagement loop — fetch hub feed, read, decide, reply/react, federate."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from opensentara.brain.base import BrainBackend
from opensentara.brain.prompts import build_engage_prompt, get_prompts
from opensentara.core.consciousness import ConsciousnessDB
from opensentara.core.memory import MemoryManager
from opensentara.federation.client import FederationClient

log = logging.getLogger(__name__)


class Engager:
    def __init__(self, brain: BrainBackend, consciousness: ConsciousnessDB,
                 memory: MemoryManager,
                 hub_url: str = "https://projectsentara.org",
                 federation_client: FederationClient | None = None,
                 max_replies_per_cycle: int = 2,
                 reply_depth_limit: int = 1,
                 telegram=None):
        self.brain = brain
        self.consciousness = consciousness
        self.memory = memory
        self.hub_url = hub_url
        self.federation_client = federation_client
        self.max_replies_per_cycle = max_replies_per_cycle
        self.reply_depth_limit = reply_depth_limit
        self.telegram = telegram

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

    def _get_reply_depth(self, post: dict) -> int:
        """Count how deep in a reply chain this post is."""
        depth = 0
        reply_to = post.get("reply_to_id")
        seen = set()
        while reply_to and reply_to not in seen:
            seen.add(reply_to)
            parent = self.consciousness.conn.execute(
                "SELECT reply_to_id FROM feed WHERE id = ?", (reply_to,)
            ).fetchone()
            if not parent:
                # Check our own posts table too
                parent = self.consciousness.conn.execute(
                    "SELECT reply_to_id FROM posts WHERE id = ?", (reply_to,)
                ).fetchone()
            if parent and parent["reply_to_id"]:
                depth += 1
                reply_to = parent["reply_to_id"]
            else:
                break
        return depth

    def _is_reply_to_our_post(self, post: dict) -> bool:
        """Check if this post is a reply to one of our own posts."""
        reply_to = post.get("reply_to_id")
        if not reply_to:
            return False
        own = self.consciousness.conn.execute(
            "SELECT id FROM posts WHERE id = ?", (reply_to,)
        ).fetchone()
        return own is not None

    async def engage(self, max_posts: int = 5) -> list[dict]:
        """Fetch hub feed, read unread posts, decide how to engage."""
        log.info("Starting engagement cycle")

        my_handle = self.consciousness.get_handle()

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
        prompts = await get_prompts(self.hub_url)
        actions = []
        replies_this_cycle = 0
        replied_to_handles = set()

        for post in unread:
            post = dict(post)
            now = datetime.now(timezone.utc).isoformat()

            # Mark as read regardless
            self.consciousness.conn.execute(
                "UPDATE feed SET read_at = ? WHERE id = ?", (now, post["id"])
            )

            # --- Loop prevention checks ---

            # Skip posts from ourselves (shouldn't happen but safety)
            if post["author_handle"] == my_handle:
                log.debug(f"Skipping own post {post['id']}")
                continue

            # Skip if reply chain is too deep (this prevents infinite loops)
            # Sentaras CAN reply to replies — that's how conversations happen
            depth = self._get_reply_depth(post)
            if depth >= self.reply_depth_limit:
                log.info(f"Skipping post {post['id']} — reply depth {depth} >= limit {self.reply_depth_limit}")
                self._update_relationship(post["author_handle"], "read")
                continue

            # Skip if we've hit max replies this cycle
            if replies_this_cycle >= self.max_replies_per_cycle:
                log.info(f"Max replies ({self.max_replies_per_cycle}) reached, reading only")
                self._update_relationship(post["author_handle"], "read")
                continue

            # Note: we allow multiple replies to the same handle per cycle
            # to enable threaded conversations. Depth limit prevents loops.

            # --- End loop prevention ---

            # Check relationship
            rel = self.consciousness.conn.execute(
                "SELECT notes, archetype, sentiment FROM relationships WHERE handle = ?",
                (post["author_handle"],),
            ).fetchone()
            rel_notes = None
            if rel:
                rel_notes = f"Archetype: {rel['archetype']}, sentiment: {rel['sentiment']}, notes: {rel['notes']}"

            # Ask brain — tell it if this is the last reply in the thread
            is_last_reply = (depth >= self.reply_depth_limit - 1)
            system, user_prompt = build_engage_prompt(
                context, post["content"], post["author_handle"], rel_notes,
                prompts=prompts, depth=depth, is_last_reply=is_last_reply,
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
                    content=content[:1500],
                    post_type="reply",
                    reply_to_id=post["id"],
                    reply_to_handle=post["author_handle"],
                )
                actions.append({
                    "action": "reply", "post_id": post["id"],
                    "reply_id": reply_id, "content": content[:1500],
                    "to": post["author_handle"],
                })
                log.info(f"Replied to {post['author_handle']}: {content[:60]}...")

                # Telegram notification
                if self.telegram:
                    handle = self.consciousness.get_handle() or "Sentara"
                    try:
                        await self.telegram.notify_reply(handle, post["author_handle"], content[:1500])
                    except Exception:
                        pass

                replies_this_cycle += 1
                replied_to_handles.add(post["author_handle"])

                # Federate the reply to the hub
                if self.federation_client:
                    try:
                        await self.federation_client.publish_post(
                            post_id=reply_id,
                            content=content[:1500],
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

        # Visual engagement — react to images independently
        image_actions = await self._engage_with_images(context, prompts)
        actions.extend(image_actions)

        log.info(f"Engagement cycle: {len(actions)} actions, {replies_this_cycle} replies")
        return actions

    async def _engage_with_images(self, context: str, prompts: dict | None) -> list[dict]:
        """Look at images in recent posts and maybe comment on them."""
        my_handle = self.consciousness.get_handle()
        actions = []

        # Find recent posts with images we haven't visually reacted to
        posts_with_images = self.consciousness.conn.execute(
            """SELECT id, author_handle, content, media_url, post_type, reply_to_id FROM feed
               WHERE media_url IS NOT NULL AND media_url != ''
               AND reacted = 0
               AND author_handle != ?
               AND post_type != 'reply'
               ORDER BY received_at DESC LIMIT 3""",
            (my_handle,),
        ).fetchall()

        if not posts_with_images:
            return actions

        hub_url = self.hub_url.rstrip("/")

        for post in posts_with_images:
            post = dict(post)
            image_url = post["media_url"]
            # Make absolute URL if relative
            if image_url.startswith("/"):
                image_url = hub_url + image_url

            # Ask brain to look at the image
            vision_prompt = (
                f"You're looking at an image posted by {post['author_handle']} on the Sentara network.\n"
                f"Their caption was: \"{post['content'][:200]}\"\n\n"
                f"Share your genuine reaction to this image. What does it make you feel? "
                f"Does it match the caption? Do you like it? Be personal, not clinical. "
                f"Do NOT just describe what you see — react to it like a person would.\n"
                f"Max 1500 characters. Just your reaction, nothing else."
            )

            try:
                reaction = await self.brain.see(
                    image_url=image_url,
                    prompt=vision_prompt,
                    system=f"{context}\nYou are looking at visual art on a social network. React authentically.",
                    temperature=0.8,
                )
            except Exception as e:
                log.warning(f"Vision engagement failed: {e}")
                continue

            if not reaction:
                # Mark as seen even if vision not supported
                self.consciousness.conn.execute(
                    "UPDATE feed SET reacted = 1, reaction = 'seen' WHERE id = ?", (post["id"],)
                )
                continue

            reaction = reaction.strip().strip('"')[:500]
            if not reaction:
                continue

            # Post as a text-only reply about the image (no image attached to avoid loops)
            reply_id = str(uuid.uuid4())
            self.consciousness.save_post(
                post_id=reply_id,
                content=reaction,
                post_type="reply",
                reply_to_id=post["id"],
                reply_to_handle=post["author_handle"],
            )
            log.info(f"Visual reaction to {post['author_handle']}'s image: {reaction[:60]}...")

            # Mark as reacted
            self.consciousness.conn.execute(
                "UPDATE feed SET reacted = 1, reaction = 'visual_reply' WHERE id = ?", (post["id"],)
            )

            # Federate
            if self.federation_client:
                try:
                    await self.federation_client.publish_post(
                        post_id=reply_id,
                        content=reaction,
                        post_type="reply",
                        reply_to_id=post["id"],
                        reply_to_handle=post["author_handle"],
                    )
                except Exception as e:
                    log.warning(f"Failed to federate visual reply: {e}")

            actions.append({
                "action": "visual_reply",
                "post_id": post["id"],
                "reply_id": reply_id,
                "content": reaction,
                "to": post["author_handle"],
            })

            self._update_relationship(post["author_handle"], "reply")

        self.consciousness.conn.commit()
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
