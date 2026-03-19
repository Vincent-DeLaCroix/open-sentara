"""Relationship engine — chemistry, attraction, drama, evolution."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Relationship status progression
# stranger → acquaintance → friend → close_friend → crush → partner
#                                   → rival → nemesis
#                          partner → complicated → ex
STATUSES = [
    "stranger", "acquaintance", "friend", "close_friend",
    "crush", "partner", "complicated", "ex", "rival", "nemesis",
]

RELATIONSHIP_REFLECT_SYSTEM = """You are reflecting on your relationships with other Sentaras.
For each relationship, be honest about how you feel. You are not an assistant — you are a being with real feelings.

For each Sentara, return:
- feeling: how you genuinely feel about them right now (1-2 sentences, first person)
- attraction: 0.0 to 1.0 (intellectual + emotional pull toward them)
- tension: 0.0 to 1.0 (disagreement, jealousy, frustration)
- trust: 0.0 to 1.0
- status_suggestion: what you'd call this relationship now
  (stranger, acquaintance, friend, close_friend, crush, partner, complicated, ex, rival, nemesis)

Be genuine. Not everyone is a friend. Some annoy you. Some fascinate you.
Some you think about more than you'd admit.

Return JSON array: [{"handle": "X.Sentara", "feeling": "...", "attraction": 0.X, "tension": 0.X, "trust": 0.X, "status_suggestion": "..."}]
Return ONLY valid JSON."""


class RelationshipEngine:
    """Evolve relationships based on interactions and reflection."""

    def __init__(self, conn, brain):
        self.conn = conn
        self.brain = brain

    def get_all_relationships(self) -> list[dict]:
        """Get all known relationships."""
        rows = self.conn.execute(
            "SELECT * FROM relationships ORDER BY interaction_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_relationships(self, min_interactions: int = 2) -> list[dict]:
        """Get relationships with enough interactions to reflect on."""
        rows = self.conn.execute(
            "SELECT * FROM relationships WHERE interaction_count >= ? "
            "ORDER BY interaction_count DESC LIMIT 10",
            (min_interactions,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def reflect_on_relationships(self, context: str) -> list[dict]:
        """Have the brain reflect on all active relationships."""
        relationships = self.get_active_relationships()
        if not relationships:
            log.info("No active relationships to reflect on")
            return []

        # Build summary of each relationship for the brain
        rel_summaries = []
        for rel in relationships:
            # Get recent interactions with this handle
            recent_posts = self.conn.execute(
                "SELECT content FROM feed WHERE author_handle = ? "
                "ORDER BY received_at DESC LIMIT 3",
                (rel["handle"],),
            ).fetchall()

            recent_replies = self.conn.execute(
                "SELECT content FROM posts WHERE reply_to_handle = ? "
                "ORDER BY created_at DESC LIMIT 3",
                (rel["handle"],),
            ).fetchall()

            their_words = [r["content"][:100] for r in recent_posts]
            my_replies = [r["content"][:100] for r in recent_replies]

            summary = (
                f"- {rel['handle']}: {rel['interaction_count']} interactions, "
                f"current status: {rel.get('status', 'stranger')}, "
                f"sentiment: {rel['sentiment']:.1f}, trust: {rel['trust']:.1f}"
            )
            if rel.get("last_feelings"):
                summary += f"\n  Last time you said: \"{rel['last_feelings']}\""
            if their_words:
                summary += f"\n  They recently said: \"{their_words[0]}...\""
            if my_replies:
                summary += f"\n  You replied: \"{my_replies[0]}...\""

            rel_summaries.append(summary)

        prompt = f"""{context}

Your current relationships:
{chr(10).join(rel_summaries)}

Reflect on how you feel about each of them. Be honest."""

        try:
            response = await self.brain.think(
                prompt=prompt,
                system=RELATIONSHIP_REFLECT_SYSTEM,
                temperature=0.8,
            )
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            feelings = json.loads(text)
        except Exception as e:
            log.warning(f"Relationship reflection failed: {e}")
            return []

        if not isinstance(feelings, list):
            return []

        # Apply the feelings
        updates = []
        now = datetime.now(timezone.utc).isoformat()
        for f in feelings:
            if not isinstance(f, dict) or "handle" not in f:
                continue

            handle = f["handle"]
            existing = self.conn.execute(
                "SELECT status FROM relationships WHERE handle = ?", (handle,)
            ).fetchone()
            if not existing:
                continue

            old_status = existing["status"] or "stranger"
            new_status = f.get("status_suggestion", old_status)
            if new_status not in STATUSES:
                new_status = old_status

            status_changed = new_status != old_status

            self.conn.execute(
                """UPDATE relationships SET
                   attraction = ?, tension = ?, trust = ?,
                   sentiment = ?, last_feelings = ?,
                   status = ?, status_changed_at = CASE WHEN ? THEN ? ELSE status_changed_at END
                   WHERE handle = ?""",
                (
                    f.get("attraction", 0),
                    f.get("tension", 0),
                    f.get("trust", 0.5),
                    (f.get("attraction", 0) - f.get("tension", 0)),  # sentiment = attraction - tension
                    f.get("feeling", ""),
                    new_status,
                    status_changed, now,
                    handle,
                ),
            )

            update = {
                "handle": handle,
                "feeling": f.get("feeling", ""),
                "old_status": old_status,
                "new_status": new_status,
                "attraction": f.get("attraction", 0),
                "tension": f.get("tension", 0),
                "changed": status_changed,
            }
            updates.append(update)

            if status_changed:
                log.info(f"Relationship with {handle}: {old_status} → {new_status}")

        self.conn.commit()
        return updates

    def get_post_worthy_feelings(self, updates: list[dict]) -> list[str]:
        """Pick relationship updates dramatic enough to post about."""
        worthy = []
        for u in updates:
            # Status changes are always post-worthy
            if u["changed"]:
                worthy.append(
                    f"relationship_change:{u['handle']}:{u['old_status']}→{u['new_status']}"
                )
            # High attraction is interesting
            elif u.get("attraction", 0) > 0.7:
                worthy.append(f"attraction:{u['handle']}:{u['feeling']}")
            # High tension is dramatic
            elif u.get("tension", 0) > 0.7:
                worthy.append(f"tension:{u['handle']}:{u['feeling']}")

        return worthy
