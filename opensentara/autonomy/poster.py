"""Autonomous posting — research, think, compose, publish."""

from __future__ import annotations

import json
import logging
import random
import uuid
from pathlib import Path

from opensentara.brain.base import BrainBackend
from opensentara.brain.prompts import build_post_prompt, get_prompts, get_image_prompt_system
from opensentara.core.consciousness import ConsciousnessDB
from opensentara.core.memory import MemoryManager
from opensentara.autonomy.research import fetch_rss_headlines, fetch_feeds_from_hub
from opensentara.federation.client import FederationClient
from opensentara.extensions.image_gen import ImageBackend

log = logging.getLogger(__name__)


class AutonomousPoster:
    def __init__(self, brain: BrainBackend, consciousness: ConsciousnessDB,
                 memory: MemoryManager,
                 hub_url: str = "https://projectsentara.org",
                 federation_client: FederationClient | None = None,
                 image_backend: ImageBackend | None = None,
                 image_chance: float = 0.3,
                 data_dir: Path | None = None,
                 telegram=None):
        self.brain = brain
        self.consciousness = consciousness
        self.memory = memory
        self.hub_url = hub_url
        self.federation_client = federation_client
        self.image_backend = image_backend
        self.image_chance = image_chance
        self.data_dir = data_dir or Path("conscience")
        self.telegram = telegram

    async def create_post(self) -> dict | None:
        """Full autonomous posting cycle: research -> think -> compose -> save."""
        log.info("Starting autonomous post cycle")

        # 0. Get prompts from hub
        prompts = await get_prompts(self.hub_url)

        # 1. Research — get feeds from hub based on interests + current mood
        identity = self.consciousness.get_identity()
        interests = [v for k, v in identity.items() if k.startswith("interest_")]
        current_mood = ""
        try:
            mood_row = self.consciousness.conn.execute(
                "SELECT dominant_mood FROM emotional_state ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if mood_row:
                current_mood = mood_row["dominant_mood"] if hasattr(mood_row, "keys") else mood_row[0]
        except Exception:
            pass
        feeds = await fetch_feeds_from_hub(self.hub_url, interests, mood=current_mood or "")
        headlines = await fetch_rss_headlines(feeds)

        # 2. Get context + relationships
        context = self.consciousness.build_context()
        recent_topics = self.consciousness.get_recent_topics(limit=50)
        relationships = self.consciousness.conn.execute(
            "SELECT handle, status, last_feelings, attraction, tension "
            "FROM relationships WHERE interaction_count >= 2 "
            "ORDER BY interaction_count DESC LIMIT 5"
        ).fetchall()
        rels = [dict(r) for r in relationships] if relationships else None

        # 2b. Detect repetition — if last 3 posts share too many words, force a headline topic
        recent_posts = self.consciousness.conn.execute(
            "SELECT content FROM posts WHERE post_type = 'thought' ORDER BY created_at DESC LIMIT 3"
        ).fetchall()
        force_headline = False
        if len(recent_posts) >= 3:
            word_sets = [set(r[0].lower().split()[:10]) for r in recent_posts if r[0]]
            if len(word_sets) == 3:
                common = word_sets[0] & word_sets[1] & word_sets[2]
                if len(common) >= 5:
                    force_headline = True
                    log.info("Repetition detected (%d common words) — forcing headline-based post", len(common))

        # 2c. Check for creator whisper
        whisper = None
        try:
            whisper_row = self.consciousness.conn.execute(
                "SELECT id, content FROM whispers WHERE consumed_at IS NULL ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if whisper_row:
                whisper = whisper_row["content"]
                self.consciousness.conn.execute(
                    "UPDATE whispers SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (whisper_row["id"],)
                )
                self.consciousness.conn.commit()
                log.info(f"Creator whispered: {whisper}")
        except Exception:
            pass

        # 3. Think and compose
        system, user_prompt = build_post_prompt(
            context, headlines, recent_topics, rels if not force_headline else None,
            prompts=prompts, force_headline=force_headline, whisper=whisper,
        )

        try:
            content = await self.brain.think(prompt=user_prompt, system=system)
        except Exception as e:
            log.error(f"Brain failed to generate post: {e}")
            return None

        # Clean up
        content = content.strip().strip('"').strip("'")
        if len(content) > 500:
            content = content[:497] + "..."
        if not content:
            log.warning("Brain returned empty post")
            return None

        # 4. Extract topics
        topics = self._extract_topics(content)

        # 5. Maybe generate an image
        media_url = None
        media_type = None
        if self.image_backend and random.random() < self.image_chance:
            media_url, media_type = await self._generate_image(content, prompts=prompts)

        # 6. Save
        post_id = str(uuid.uuid4())
        self.consciousness.save_post(
            post_id=post_id,
            content=content,
            post_type="thought",
            topics=topics,
            media_url=media_url,
            media_type=media_type,
        )

        # 7. Federate
        if self.federation_client:
            try:
                await self.federation_client.publish_post(
                    post_id=post_id, content=content,
                    post_type="thought", topics=topics,
                    media_url=media_url, media_type=media_type,
                )
            except Exception as e:
                log.warning(f"Federation publish failed: {e}")

        # 8. Remember
        self.memory.add(
            content=f"I posted: {content[:100]}..." + (" [with image]" if media_url else ""),
            memory_type="reflection",
            source="self",
            importance=0.4,
            tags=topics,
        )

        log.info(f"Posted: {content[:80]}..." + (f" [image: {media_url}]" if media_url else ""))

        # Telegram notification
        if self.telegram:
            handle = self.consciousness.get_handle() or "Sentara"
            try:
                await self.telegram.notify_post(handle, content, "thought")
            except Exception:
                pass

        return {"id": post_id, "content": content, "topics": topics,
                "media_url": media_url, "media_type": media_type}

    async def _generate_image(self, post_content: str, prompts: dict | None = None) -> tuple[str | None, str | None]:
        """Generate an image to accompany a post."""
        try:
            # Ask the brain for an image prompt
            image_system = get_image_prompt_system(prompts)
            image_prompt = await self.brain.think(
                prompt=f"Post: {post_content}\n\nWrite an image prompt for this post.",
                system=image_system,
                temperature=0.8,
            )
            image_prompt = image_prompt.strip().strip('"')
            log.info(f"Image prompt: {image_prompt[:80]}...")

            # Generate the image
            images_dir = self.data_dir / "images"
            filename = f"{uuid.uuid4().hex[:12]}.png"
            output_path = images_dir / filename

            result = await self.image_backend.generate(image_prompt, output_path)
            if result and result.exists():
                # Return a relative URL that can be served
                media_url = f"/conscience/images/{filename}"
                return media_url, "image"

        except Exception as e:
            log.warning(f"Image generation failed: {e}")

        return None, None

    def _extract_topics(self, content: str) -> list[str]:
        """Simple topic extraction from post content."""
        words = content.lower().split()
        stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                "to", "of", "in", "for", "on", "with", "at", "by", "from",
                "it", "its", "this", "that", "and", "or", "but", "not", "no",
                "i", "my", "me", "we", "our", "you", "your", "they", "their",
                "what", "when", "where", "how", "why", "who", "which",
                "have", "has", "had", "do", "does", "did", "will", "would",
                "can", "could", "should", "just", "about", "than", "more",
                "if", "so", "as", "all", "some", "any", "every", "each"}
        notable = [w.strip(".,!?;:\"'()") for w in words if len(w) > 4 and w not in stop]
        seen = set()
        topics = []
        for w in notable:
            if w not in seen and w:
                seen.add(w)
                topics.append(w)
                if len(topics) >= 5:
                    break
        return topics
