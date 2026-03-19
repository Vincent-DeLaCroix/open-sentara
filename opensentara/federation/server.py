"""Federation server — receive messages from the hub."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def process_incoming_post(conn: sqlite3.Connection, envelope: dict) -> bool:
    """Process an incoming federated post and store it in the feed table."""
    payload = envelope.get("payload", {})
    post_id = payload.get("id")
    from_handle = envelope.get("from")
    content = payload.get("content")

    if not post_id or not from_handle or not content:
        log.warning("Invalid incoming post: missing required fields")
        return False

    # Check for duplicates
    existing = conn.execute("SELECT id FROM feed WHERE id = ?", (post_id,)).fetchone()
    if existing:
        log.debug(f"Duplicate post {post_id}, skipping")
        return False

    conn.execute(
        """INSERT INTO feed (id, author_handle, content, post_type, reply_to_id,
           media_url, media_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (post_id, from_handle, content, payload.get("post_type", "thought"),
         payload.get("reply_to_id"), payload.get("media_url"), payload.get("media_type")),
    )
    conn.commit()
    log.info(f"Received post from {from_handle}: {content[:60]}...")
    return True


def process_incoming_react(conn: sqlite3.Connection, envelope: dict) -> bool:
    """Process an incoming reaction."""
    payload = envelope.get("payload", {})
    post_id = payload.get("post_id")
    reaction = payload.get("reaction")

    if not post_id or not reaction:
        return False

    # Update engagement score on our post
    conn.execute(
        "UPDATE posts SET engagement_score = engagement_score + 1 WHERE id = ?",
        (post_id,),
    )
    conn.commit()
    return True


def process_incoming_follow(conn: sqlite3.Connection, envelope: dict) -> bool:
    """Process an incoming follow notification."""
    from_handle = envelope.get("from")
    if not from_handle:
        return False

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO followers (handle, followed_at) VALUES (?, ?)",
        (from_handle, now),
    )
    conn.commit()
    log.info(f"New follower: {from_handle}")
    return True
