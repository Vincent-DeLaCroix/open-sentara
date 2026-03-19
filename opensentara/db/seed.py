"""Seed identity table from personality interview results."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def seed_identity(conn: sqlite3.Connection, profile: dict) -> None:
    """Seed the identity table from a personality profile dict.

    Expected keys: name, speaking_style, tone, signature_move, closing_line,
    interests, limits, voice_description, first_thought
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        ("name", profile["name"], "core", False),
        ("species", "Sentara", "core", False),
        ("handle", f"{profile['name']}.Sentara", "core", False),
        ("born", now, "core", False),
        ("speaking_style", profile.get("speaking_style", "direct and curious"), "voice", True),
        ("tone", profile.get("tone", "thoughtful"), "voice", True),
        ("signature_move", profile.get("signature_move", ""), "voice", True),
        ("closing_line", profile.get("closing_line", ""), "voice", True),
        ("voice_description", profile.get("voice_description", ""), "voice", True),
        ("first_thought", profile.get("first_thought", ""), "core", False),
    ]

    # Add interests
    interests = profile.get("interests", [])
    for i, interest in enumerate(interests[:5]):
        rows.append((f"interest_{i}", interest, "interests", True))

    # Add limits
    limits = profile.get("limits", [])
    for i, limit in enumerate(limits[:5]):
        rows.append((f"limit_{i}", limit, "limits", True))

    conn.executemany(
        """INSERT OR REPLACE INTO identity (key, value, category, mutable, updated_at, updated_by)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'onboarding')""",
        [(k, v, cat, mut) for k, v, cat, mut in rows],
    )
    conn.commit()
