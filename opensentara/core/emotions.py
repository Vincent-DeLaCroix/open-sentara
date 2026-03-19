"""Emotional state tracking — 5 dimensions."""

from __future__ import annotations

import sqlite3
from datetime import date


DIMENSIONS = ["curiosity", "confidence", "frustration", "wonder", "concern"]


class EmotionalState:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_current(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM emotional_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def update(self, curiosity: float, confidence: float, frustration: float,
               wonder: float, concern: float,
               dominant_mood: str | None = None,
               mood_trigger: str | None = None) -> None:
        today = date.today().isoformat()

        # Auto-detect dominant mood
        if not dominant_mood:
            scores = {
                "curious": curiosity, "confident": confidence,
                "frustrated": frustration, "wondering": wonder, "concerned": concern
            }
            dominant_mood = max(scores, key=scores.get)

        self.conn.execute(
            """INSERT INTO emotional_state (date, curiosity, confidence, frustration,
               wonder, concern, dominant_mood, mood_trigger)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (today, curiosity, confidence, frustration, wonder, concern,
             dominant_mood, mood_trigger),
        )
        self.conn.commit()

    def get_history(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM emotional_state ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
