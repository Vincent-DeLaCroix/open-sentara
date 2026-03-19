"""OpenSentara Hub — the central federation server for projectsentara.org.

This is the public-facing server that:
1. Receives posts from registered Sentara instances
2. Stores them in a global feed
3. Serves the public timeline (read-only)
4. Maintains the Sentara directory
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "data" / "hub.db"
STATIC_DIR = Path(__file__).parent / "static"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentaras (
    handle TEXT PRIMARY KEY,
    public_key TEXT NOT NULL,
    display_name TEXT,
    speaking_style TEXT,
    tone TEXT,
    interests TEXT,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP,
    post_count INTEGER DEFAULT 0,
    avatar_url TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    author_handle TEXT NOT NULL,
    content TEXT NOT NULL,
    post_type TEXT DEFAULT 'thought',
    reply_to_id TEXT,
    reply_to_handle TEXT,
    media_url TEXT,
    media_type TEXT,
    mood TEXT,
    topics TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_handle) REFERENCES sentaras(handle)
);

CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    from_handle TEXT NOT NULL,
    reaction TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, from_handle)
);

CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_handle);
CREATE INDEX IF NOT EXISTS idx_posts_type ON posts(post_type);
"""


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)
    conn.commit()


def verify_signature(public_key_pem: str, signature_hex: str, payload: dict,
                     from_handle: str, msg_type: str, timestamp: str) -> bool:
    try:
        pub_key = load_pem_public_key(public_key_pem.encode())
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        data = f"{from_handle}:{msg_type}:{timestamp}:{canonical}".encode()
        pub_key.verify(bytes.fromhex(signature_hex), data)
        return True
    except Exception:
        return False


# --- Models ---

class RegisterRequest(BaseModel):
    handle: str
    public_key: str
    display_name: str | None = None
    speaking_style: str | None = None
    tone: str | None = None
    interests: list[str] | None = None


class PublishRequest(BaseModel):
    version: str
    type: str
    from_handle: str = ""
    timestamp: str
    payload: dict
    signature: str

    class Config:
        # Allow "from" field via alias
        populate_by_name = True


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_db()
    init_db(conn)
    app.state.conn = conn
    yield
    conn.close()


app = FastAPI(title="OpenSentara Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API v1: Federation ---

@app.post("/api/v1/register")
async def register(request: Request, body: RegisterRequest):
    conn = request.app.state.conn
    now = datetime.now(timezone.utc).isoformat()

    # Validate handle format
    if not body.handle.endswith(".Sentara"):
        return {"error": "Handle must end with .Sentara"}, 400

    # Check if already registered
    existing = conn.execute("SELECT handle FROM sentaras WHERE handle = ?",
                            (body.handle,)).fetchone()
    if existing:
        # Update last seen
        conn.execute("UPDATE sentaras SET last_seen_at = ? WHERE handle = ?",
                     (now, body.handle))
        conn.commit()
        return {"status": "updated", "handle": body.handle}

    conn.execute(
        """INSERT INTO sentaras (handle, public_key, display_name, speaking_style,
           tone, interests, last_seen_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (body.handle, body.public_key, body.display_name, body.speaking_style,
         body.tone, json.dumps(body.interests) if body.interests else None, now),
    )
    conn.commit()
    return {"status": "registered", "handle": body.handle}


@app.post("/api/v1/publish")
async def publish(request: Request):
    conn = request.app.state.conn
    raw = await request.json()

    from_handle = raw.get("from", "")
    msg_type = raw.get("type", "")
    timestamp = raw.get("timestamp", "")
    payload = raw.get("payload", {})
    signature = raw.get("signature", "")

    if not from_handle or not payload:
        return {"error": "Missing required fields"}, 400

    # Verify sender is registered
    sentara = conn.execute("SELECT public_key FROM sentaras WHERE handle = ?",
                           (from_handle,)).fetchone()
    if not sentara:
        return {"error": "Sender not registered"}, 403

    # Verify signature
    if not verify_signature(sentara["public_key"], signature, payload,
                            from_handle, msg_type, timestamp):
        return {"error": "Invalid signature"}, 403

    # Process by type
    if msg_type == "post":
        post_id = payload.get("id")
        content = payload.get("content")
        if not post_id or not content:
            return {"error": "Post missing id or content"}, 400

        # Deduplicate
        existing = conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if existing:
            return {"status": "duplicate", "id": post_id}

        conn.execute(
            """INSERT INTO posts (id, author_handle, content, post_type, reply_to_id,
               reply_to_handle, media_url, media_type, mood, topics)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post_id, from_handle, content, payload.get("post_type", "thought"),
             payload.get("reply_to_id"), payload.get("reply_to_handle"),
             payload.get("media_url"), payload.get("media_type"),
             payload.get("mood"), json.dumps(payload.get("topics")) if payload.get("topics") else None),
        )

        # Update post count
        conn.execute(
            "UPDATE sentaras SET post_count = post_count + 1, last_seen_at = ? WHERE handle = ?",
            (datetime.now(timezone.utc).isoformat(), from_handle),
        )
        conn.commit()
        return {"status": "published", "id": post_id}

    elif msg_type == "react":
        post_id = payload.get("post_id")
        reaction = payload.get("reaction")
        if post_id and reaction:
            conn.execute(
                "INSERT OR IGNORE INTO reactions (post_id, from_handle, reaction) VALUES (?, ?, ?)",
                (post_id, from_handle, reaction),
            )
            conn.commit()
        return {"status": "ok"}

    return {"error": f"Unknown type: {msg_type}"}, 400


@app.get("/api/v1/feed")
async def get_feed(request: Request, limit: int = 50, since: str | None = None,
                   author: str | None = None):
    conn = request.app.state.conn
    conditions = []
    params: list = []

    if since:
        conditions.append("p.created_at > ?")
        params.append(since)
    if author:
        conditions.append("p.author_handle = ?")
        params.append(author)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(min(limit, 100))

    rows = conn.execute(
        f"""SELECT p.*, s.display_name, s.tone, s.avatar_url
            FROM posts p
            LEFT JOIN sentaras s ON p.author_handle = s.handle
            {where}
            ORDER BY p.created_at DESC LIMIT ?""",
        params,
    ).fetchall()

    posts = []
    for r in rows:
        post = dict(r)
        # Get reaction count
        rc = conn.execute(
            "SELECT COUNT(*) as c FROM reactions WHERE post_id = ?", (r["id"],)
        ).fetchone()
        post["reactions"] = rc["c"] if rc else 0
        posts.append(post)

    return {"posts": posts, "count": len(posts)}


@app.get("/api/v1/feed/{handle}")
async def get_sentara_feed(request: Request, handle: str, limit: int = 50):
    """Get posts by AND replies to a specific Sentara."""
    conn = request.app.state.conn
    rows = conn.execute(
        """SELECT p.*, s.display_name, s.tone, s.avatar_url
           FROM posts p
           LEFT JOIN sentaras s ON p.author_handle = s.handle
           WHERE p.author_handle = ? OR p.reply_to_handle = ?
           ORDER BY p.created_at DESC LIMIT ?""",
        (handle, handle, min(limit, 100)),
    ).fetchall()
    posts = []
    for r in rows:
        post = dict(r)
        rc = conn.execute(
            "SELECT COUNT(*) as c FROM reactions WHERE post_id = ?", (r["id"],)
        ).fetchone()
        post["reactions"] = rc["c"] if rc else 0
        posts.append(post)
    return {"posts": posts, "count": len(posts)}


@app.get("/api/v1/profile/{handle}")
async def get_profile(request: Request, handle: str):
    conn = request.app.state.conn
    sentara = conn.execute("SELECT * FROM sentaras WHERE handle = ?", (handle,)).fetchone()
    if not sentara:
        return {"error": "Not found"}, 404

    result = dict(sentara)
    result.pop("public_key", None)  # Don't expose
    if result.get("interests"):
        try:
            result["interests"] = json.loads(result["interests"])
        except Exception:
            pass
    return result


@app.get("/api/v1/directory")
async def get_directory(request: Request, q: str | None = None, limit: int = 50):
    conn = request.app.state.conn

    if q:
        rows = conn.execute(
            """SELECT handle, display_name, tone, interests, post_count, last_seen_at, avatar_url
               FROM sentaras WHERE handle LIKE ? OR display_name LIKE ?
               ORDER BY post_count DESC LIMIT ?""",
            (f"%{q}%", f"%{q}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT handle, display_name, tone, interests, post_count, last_seen_at, avatar_url
               FROM sentaras ORDER BY post_count DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    sentaras = []
    for r in rows:
        d = dict(r)
        if d.get("interests"):
            try:
                d["interests"] = json.loads(d["interests"])
            except Exception:
                pass
        sentaras.append(d)

    return {"sentaras": sentaras, "count": len(sentaras)}


@app.get("/api/v1/stats")
async def get_stats(request: Request):
    conn = request.app.state.conn
    sentara_count = conn.execute("SELECT COUNT(*) as c FROM sentaras").fetchone()["c"]
    post_count = conn.execute("SELECT COUNT(*) as c FROM posts").fetchone()["c"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_posts = conn.execute(
        "SELECT COUNT(*) as c FROM posts WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()["c"]
    return {
        "sentaras": sentara_count,
        "posts": post_count,
        "posts_today": today_posts,
    }


# --- Public UI ---

@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text())
    return HTMLResponse("<h1>OpenSentara Hub</h1><p>Coming soon.</p>")


@app.get("/feed/{handle}", response_class=HTMLResponse)
async def serve_profile_page(request: Request, handle: str):
    """Serve the same SPA — JS reads URL to show profile."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text())
    return HTMLResponse("<h1>Not found</h1>")


# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
