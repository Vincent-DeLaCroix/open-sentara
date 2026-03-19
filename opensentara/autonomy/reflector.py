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

log = logging.getLogger(__name__)


class Reflector:
    def __init__(self, brain: BrainBackend, consciousness: ConsciousnessDB,
                 emotions: EmotionalState, opinions: OpinionTracker,
                 evolution: EvolutionLog, memory: MemoryManager):
        self.brain = brain
        self.consciousness = consciousness
        self.emotions = emotions
        self.opinions = opinions
        self.evolution = evolution
        self.memory = memory

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

        self.consciousness.conn.commit()
        log.info(f"Reflection complete. Mood: {result.get('dominant_mood')}")
        return result
