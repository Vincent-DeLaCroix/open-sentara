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


_ALLOWED_TABLES = {"relationships", "posts", "feed", "identity", "memories", "opinions",
                    "diary", "evolution", "emotional_state", "following", "followers"}
_ALLOWED_COL_PATTERN = __import__("re").compile(r'^[a-z_]+$')
_ALLOWED_DEF_PATTERN = __import__("re").compile(r'^[A-Z \'0-9._]+$')


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing databases without losing data."""
    new_cols = {
        "relationships": [
            ("chemistry", "REAL DEFAULT 0"),
            ("attraction", "REAL DEFAULT 0"),
            ("tension", "REAL DEFAULT 0"),
            ("status", "TEXT DEFAULT 'stranger'"),
            ("status_changed_at", "TIMESTAMP"),
            ("last_feelings", "TEXT"),
        ],
    }
    for table, cols in new_cols.items():
        # Whitelist validation
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Migration blocked: unknown table '{table}'")
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_def in cols:
            if not _ALLOWED_COL_PATTERN.match(col_name):
                raise ValueError(f"Migration blocked: invalid column name '{col_name}'")
            if not _ALLOWED_DEF_PATTERN.match(col_def):
                raise ValueError(f"Migration blocked: invalid column def '{col_def}'")
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
    conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize database with schema, return connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(db_path)
    schema = _SCHEMA_PATH.read_text()
    conn.executescript(schema)
    _migrate(conn)
    conn.commit()
    return conn


def is_setup_complete(conn: sqlite3.Connection) -> bool:
    """Check if initial setup has been completed."""
    row = conn.execute(
        "SELECT value FROM identity WHERE key = 'name'"
    ).fetchone()
    return row is not None
