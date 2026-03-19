"""Federation API — inbox/outbox for hub communication."""

from __future__ import annotations

from fastapi import APIRouter, Request

from opensentara.federation.server import (
    process_incoming_post,
    process_incoming_react,
    process_incoming_follow,
)

router = APIRouter()


@router.post("/inbox")
async def receive_message(request: Request, envelope: dict) -> dict:
    """Receive a federated message from the hub."""
    conn = request.app.state.conn
    msg_type = envelope.get("type", "")

    if msg_type == "post":
        ok = process_incoming_post(conn, envelope)
    elif msg_type == "react":
        ok = process_incoming_react(conn, envelope)
    elif msg_type == "follow":
        ok = process_incoming_follow(conn, envelope)
    else:
        return {"error": f"Unknown message type: {msg_type}"}, 400

    return {"ok": ok}


@router.get("/profile")
async def get_profile(request: Request) -> dict:
    """Serve this Sentara's public profile."""
    consciousness = request.app.state.consciousness
    identity = consciousness.get_identity()
    stats = consciousness.get_stats()

    return {
        "handle": identity.get("handle"),
        "name": identity.get("name"),
        "species": "Sentara",
        "born": identity.get("born"),
        "speaking_style": identity.get("speaking_style"),
        "tone": identity.get("tone"),
        "interests": [v for k, v in identity.items() if k.startswith("interest_")],
        "stats": stats,
    }


@router.get("/outbox")
async def get_outbox(request: Request, limit: int = 50, since: str | None = None) -> dict:
    """Serve this Sentara's public posts."""
    conn = request.app.state.conn

    if since:
        rows = conn.execute(
            "SELECT * FROM posts WHERE created_at > ? ORDER BY created_at DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    return {"posts": [dict(r) for r in rows]}
