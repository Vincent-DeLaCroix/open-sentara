"""Database initialization and access."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db(db_path: Path) -> sqlite3.Connection:
    """Get a database connection with WAL mode and row factory."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize database with schema, return connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(db_path)
    schema = _SCHEMA_PATH.read_text()
    conn.executescript(schema)
    conn.commit()
    return conn


def is_setup_complete(conn: sqlite3.Connection) -> bool:
    """Check if initial setup has been completed."""
    row = conn.execute(
        "SELECT value FROM identity WHERE key = 'name'"
    ).fetchone()
    return row is not None
