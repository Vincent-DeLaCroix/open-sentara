"""Opinion tracking with evolution."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class OpinionTracker:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_current(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM opinions WHERE is_current = 1 ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_on_topic(self, topic: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM opinions WHERE topic = ? AND is_current = 1",
            (topic,),
        ).fetchone()
        return dict(row) if row else None

    def form(self, topic: str, position: str, confidence: float = 0.5,
             reasoning: str | None = None) -> int:
        """Form a new opinion or update existing one."""
        existing = self.get_on_topic(topic)
        now = datetime.now(timezone.utc).isoformat()

        if existing:
            # Supersede old opinion
            self.conn.execute(
                "UPDATE opinions SET is_current = 0 WHERE id = ?", (existing["id"],)
            )
            version = existing["version"] + 1
        else:
            version = 1

        cur = self.conn.execute(
            """INSERT INTO opinions (topic, position, confidence, reasoning,
               updated_at, version)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (topic, position, confidence, reasoning, now, version),
        )
        self.conn.commit()
        return cur.lastrowid
