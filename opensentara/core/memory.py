"""Memory management with decay."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


class MemoryManager:
    """Add, recall, decay, and archive memories."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, content: str, memory_type: str = "reflection",
            context: str | None = None, source: str = "self",
            source_id: str | None = None, sentiment: float = 0.0,
            importance: float = 0.5, tags: list[str] | None = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO memories (type, content, context, source, source_id,
               sentiment, importance, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (memory_type, content, context, source, source_id,
             sentiment, importance, json.dumps(tags) if tags else None),
        )
        self.conn.commit()
        return cur.lastrowid

    def recall(self, query: str | None = None, memory_type: str | None = None,
               limit: int = 10, min_importance: float = 0.1) -> list[dict]:
        """Recall memories, optionally filtered."""
        conditions = ["type NOT LIKE 'archived_%'", f"importance >= {min_importance}"]
        params: list = []

        if memory_type:
            conditions.append("type = ?")
            params.append(memory_type)

        where = " AND ".join(conditions)
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY importance DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        # Update access count
        now = datetime.now(timezone.utc).isoformat()
        for r in rows:
            self.conn.execute(
                "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
                (now, r["id"]),
            )
        self.conn.commit()

        return [dict(r) for r in rows]

    def decay(self) -> dict[str, int]:
        """Run one decay cycle. Returns counts of decayed and archived."""
        # Decay all active memories
        self.conn.execute(
            """UPDATE memories SET importance = importance * (1.0 - decay_rate)
               WHERE importance > 0.01 AND type NOT LIKE 'archived_%'"""
        )

        # Archive faded memories
        cur = self.conn.execute(
            """UPDATE memories SET type = 'archived_' || type
               WHERE importance < 0.05 AND type NOT LIKE 'archived_%'"""
        )
        archived = cur.rowcount

        self.conn.commit()
        return {"archived": archived}

    def reinforce(self, memory_id: int, boost: float = 0.1) -> None:
        """Reinforce a memory (prevent decay)."""
        self.conn.execute(
            "UPDATE memories SET importance = MIN(1.0, importance + ?) WHERE id = ?",
            (boost, memory_id),
        )
        self.conn.commit()
