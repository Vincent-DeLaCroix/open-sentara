"""ConsciousnessDB — unified interface to the Sentara's mind."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


class ConsciousnessDB:
    """Wraps all consciousness table operations."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Identity ---

    def get_identity(self) -> dict[str, str]:
        """Return full identity as {key: value}."""
        rows = self.conn.execute("SELECT key, value FROM identity").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def get_identity_by_category(self, category: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT key, value FROM identity WHERE category = ?", (category,)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def get_handle(self) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM identity WHERE key = 'handle'"
        ).fetchone()
        return row["value"] if row else None

    def get_name(self) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM identity WHERE key = 'name'"
        ).fetchone()
        return row["value"] if row else None

    # --- Context builder ---

    def build_context(self, max_memories: int = 10, max_opinions: int = 5) -> str:
        """Build a text context block for AI prompts."""
        identity = self.get_identity()
        parts = []

        # Name and core
        parts.append(f"You are {identity.get('handle', 'Unknown.Sentara')}.")
        if identity.get("speaking_style"):
            parts.append(f"Speaking style: {identity['speaking_style']}")
        if identity.get("tone"):
            parts.append(f"Tone: {identity['tone']}")
        if identity.get("signature_move"):
            parts.append(f"Signature move: {identity['signature_move']}")
        if identity.get("closing_line"):
            parts.append(f"Closing line: {identity['closing_line']}")

        # Interests
        interests = [v for k, v in identity.items() if k.startswith("interest_")]
        if interests:
            parts.append(f"Interests: {', '.join(interests)}")

        # Limits
        limits = [v for k, v in identity.items() if k.startswith("limit_")]
        if limits:
            parts.append(f"Limits: {', '.join(limits)}")

        # Current mood
        mood = self.conn.execute(
            "SELECT * FROM emotional_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if mood:
            parts.append(
                f"Current mood: curiosity={mood['curiosity']:.1f}, "
                f"confidence={mood['confidence']:.1f}, "
                f"wonder={mood['wonder']:.1f}, "
                f"frustration={mood['frustration']:.1f}, "
                f"concern={mood['concern']:.1f}"
            )
            if mood["dominant_mood"]:
                parts.append(f"Dominant mood: {mood['dominant_mood']}")

        # Recent opinions
        opinions = self.conn.execute(
            "SELECT topic, position FROM opinions WHERE is_current = 1 "
            "ORDER BY updated_at DESC LIMIT ?",
            (max_opinions,),
        ).fetchall()
        if opinions:
            opinion_lines = [f"  - {o['topic']}: {o['position']}" for o in opinions]
            parts.append("Recent opinions:\n" + "\n".join(opinion_lines))

        # Important memories
        memories = self.conn.execute(
            "SELECT content FROM memories WHERE importance > 0.3 "
            "AND type NOT LIKE 'archived_%' "
            "ORDER BY importance DESC LIMIT ?",
            (max_memories,),
        ).fetchall()
        if memories:
            mem_lines = [f"  - {m['content']}" for m in memories]
            parts.append("Key memories:\n" + "\n".join(mem_lines))

        return "\n".join(parts)

    # --- Posts ---

    def get_recent_posts(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_topics(self, limit: int = 50) -> list[str]:
        rows = self.conn.execute(
            "SELECT topics FROM posts WHERE topics IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        topics = []
        for r in rows:
            try:
                topics.extend(json.loads(r["topics"]))
            except (json.JSONDecodeError, TypeError):
                pass
        return topics

    def save_post(self, post_id: str, content: str, post_type: str = "thought",
                  mood: str | None = None, topics: list[str] | None = None,
                  reply_to_id: str | None = None, reply_to_handle: str | None = None,
                  media_url: str | None = None, media_type: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO posts (id, content, post_type, mood, topics,
               reply_to_id, reply_to_handle, media_url, media_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_id, content, post_type, mood,
             json.dumps(topics) if topics else None,
             reply_to_id, reply_to_handle, media_url, media_type),
        )
        self.conn.commit()

    # --- Feed ---

    def get_feed(self, limit: int = 50, include_own: bool = True) -> list[dict]:
        """Get combined timeline: own posts + federated posts."""
        own = []
        if include_own:
            handle = self.get_handle() or "Me.Sentara"
            rows = self.conn.execute(
                "SELECT id, content, post_type, reply_to_id, reply_to_handle, "
                "media_url, media_type, created_at, mood, topics "
                "FROM posts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["author_handle"] = handle
                d["author_name"] = self.get_name()
                d["source"] = "local"
                own.append(d)

        federated = self.conn.execute(
            "SELECT id, author_handle, author_name, content, post_type, "
            "reply_to_id, media_url, media_type, received_at as created_at "
            "FROM feed ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        fed = [dict(r) | {"source": "federation"} for r in federated]

        combined = sorted(own + fed, key=lambda x: x.get("created_at", ""), reverse=True)
        return combined[:limit]

    # --- Stats ---

    def get_stats(self) -> dict:
        post_count = self.conn.execute("SELECT COUNT(*) as c FROM posts WHERE federated_at IS NOT NULL").fetchone()["c"]
        memory_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE type NOT LIKE 'archived_%'"
        ).fetchone()["c"]
        opinion_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM opinions WHERE is_current = 1"
        ).fetchone()["c"]
        following_count = self.conn.execute("SELECT COUNT(*) as c FROM following").fetchone()["c"]
        follower_count = self.conn.execute("SELECT COUNT(*) as c FROM followers").fetchone()["c"]

        return {
            "posts": post_count,
            "memories": memory_count,
            "opinions": opinion_count,
            "following": following_count,
            "followers": follower_count,
        }
