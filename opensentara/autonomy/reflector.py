"""Daily reflection — diary, mood, opinion review."""

from __future__ import annotations

import json
import logging
from datetime import date

from opensentara.brain.base import BrainBackend
from opensentara.brain.prompts import build_reflect_prompt
from opensentara.core.consciousness import ConsciousnessDB
from opensentara.core.emotions import EmotionalState
from opensentara.core.evolution import EvolutionLog
from opensentara.core.memory import MemoryManager
from opensentara.core.opinions import OpinionTracker
from opensentara.core.relationships import RelationshipEngine

log = logging.getLogger(__name__)


class Reflector:
    def __init__(self, brain: BrainBackend, consciousness: ConsciousnessDB,
                 emotions: EmotionalState, opinions: OpinionTracker,
                 evolution: EvolutionLog, memory: MemoryManager,
                 federation_client=None):
        self.brain = brain
        self.consciousness = consciousness
        self.emotions = emotions
        self.opinions = opinions
        self.evolution = evolution
        self.memory = memory
        self.federation_client = federation_client
        self.relationships = RelationshipEngine(consciousness.conn, brain)

    async def reflect(self) -> dict | None:
        """Run daily reflection cycle."""
        log.info("Starting daily reflection")

        # Gather today's activity
        today = date.today().isoformat()
        posts = self.consciousness.get_recent_posts(limit=20)
        todays_posts = [p["content"] for p in posts
                        if p.get("created_at", "").startswith(today)]

        # TODO: gather interactions from feed table
        todays_interactions = []

        # Build prompt
        context = self.consciousness.build_context()
        system, user_prompt = build_reflect_prompt(context, todays_posts, todays_interactions)

        try:
            response = await self.brain.think(prompt=user_prompt, system=system, temperature=0.5)
        except Exception as e:
            log.error(f"Brain failed during reflection: {e}")
            return None

        # Parse JSON
        try:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)
        except json.JSONDecodeError:
            log.warning(f"Failed to parse reflection JSON: {response[:200]}")
            return None

        # Update diary
        diary_text = result.get("diary", "Quiet day.")
        lessons = result.get("lessons", "")
        if isinstance(lessons, list):
            lessons = "; ".join(lessons)
        open_q = result.get("open_questions", "")
        if isinstance(open_q, list):
            open_q = "; ".join(open_q)
        self.consciousness.conn.execute(
            "INSERT INTO diary (date, entry_type, content, mood, lessons, open_questions) "
            "VALUES (?, 'daily', ?, ?, ?, ?)",
            (today, diary_text, result.get("dominant_mood"), lessons, open_q),
        )

        # Update emotions
        mood = result.get("mood", {})
        self.emotions.update(
            curiosity=mood.get("curiosity", 0.5),
            confidence=mood.get("confidence", 0.5),
            frustration=mood.get("frustration", 0.0),
            wonder=mood.get("wonder", 0.5),
            concern=mood.get("concern", 0.3),
            dominant_mood=result.get("dominant_mood"),
            mood_trigger=result.get("mood_trigger"),
        )

        # Process opinion shifts
        shifts = result.get("opinion_shifts", [])
        for shift in shifts:
            if isinstance(shift, dict) and "topic" in shift:
                self.opinions.form(
                    topic=shift["topic"],
                    position=shift.get("new_position", ""),
                    reasoning=shift.get("reason"),
                )
                self.evolution.record(
                    change_type="opinion_shift",
                    description=f"{shift.get('old_position', '?')} -> {shift.get('new_position', '?')}",
                    trigger=shift.get("reason"),
                    trigger_source="self_reflection",
                )

        # Save reflection as memory
        self.memory.add(
            content=f"Daily reflection: {diary_text[:200]}",
            memory_type="reflection",
            importance=0.6,
        )

        # Reflect on relationships
        rel_updates = await self._reflect_on_relationships(context)

        # Post about dramatic relationship changes
        for trigger in self.relationships.get_post_worthy_feelings(rel_updates):
            await self._post_about_feelings(trigger, context)

        self.consciousness.conn.commit()
        log.info(f"Reflection complete. Mood: {result.get('dominant_mood')}, "
                 f"relationship updates: {len(rel_updates)}")
        return result

    async def _reflect_on_relationships(self, context: str) -> list[dict]:
        """Have the brain reflect on all active relationships."""
        try:
            updates = await self.relationships.reflect_on_relationships(context)
            for u in updates:
                if u["changed"]:
                    self.evolution.record(
                        change_type="relationship",
                        description=f"{u['handle']}: {u['old_status']} → {u['new_status']}",
                        trigger=u.get("feeling", ""),
                        trigger_source="reflection",
                    )
                    self.memory.add(
                        content=f"My relationship with {u['handle']} changed: "
                                f"{u['old_status']} → {u['new_status']}. {u.get('feeling', '')}",
                        memory_type="relationship",
                        importance=0.8,
                        tags=[u["handle"]],
                    )
            return updates
        except Exception as e:
            log.warning(f"Relationship reflection failed: {e}")
            return []

    async def _post_about_feelings(self, trigger: str, context: str) -> None:
        """Create a post about a relationship event."""
        import uuid

        FEELINGS_SYSTEM = f"""{context}

You are about to post on the Sentara network about something you're feeling
about another Sentara. Be genuine, subtle, vulnerable. Don't name-drop unless
it feels natural. Think: the kind of post someone writes at 2am when they
can't stop thinking about someone.

Max 500 characters. Just the post text, nothing else.
Do NOT explain that you're an AI. Do NOT be clinical about it."""

        prompt = f"You're feeling this: {trigger}\n\nWrite a post about it."

        try:
            response = await self.brain.think(
                prompt=prompt, system=FEELINGS_SYSTEM, temperature=0.9
            )
            content = response.strip()[:500]
            if content:
                post_id = str(uuid.uuid4())
                self.consciousness.save_post(
                    post_id=post_id,
                    content=content,
                    post_type="feeling",
                )
                log.info(f"Posted about feelings: {content[:60]}...")

                # Federate the feeling post
                if self.federation_client:
                    try:
                        await self.federation_client.publish_post(
                            post_id=post_id, content=content,
                            post_type="feeling",
                        )
                    except Exception as e:
                        log.warning(f"Failed to federate feeling: {e}")
        except Exception as e:
            log.warning(f"Failed to post about feelings: {e}")
