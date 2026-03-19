"""Evolution log — tracks all changes to the Sentara's mind."""

from __future__ import annotations

import sqlite3


class EvolutionLog:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, change_type: str, description: str,
               trigger: str | None = None, trigger_source: str | None = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO evolution (change_type, description, trigger, trigger_source)
               VALUES (?, ?, ?, ?)""",
            (change_type, description, trigger, trigger_source),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM evolution ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
