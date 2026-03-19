"""Mind API — consciousness viewer endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/identity")
async def get_identity(request: Request) -> dict:
    """Get the Sentara's full identity."""
    consciousness = request.app.state.consciousness
    identity = consciousness.get_identity()
    # Group by category
    grouped = {}
    rows = request.app.state.conn.execute(
        "SELECT key, value, category, mutable FROM identity"
    ).fetchall()
    for r in rows:
        cat = r["category"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({"key": r["key"], "value": r["value"], "mutable": bool(r["mutable"])})
    return {"identity": identity, "grouped": grouped}


@router.get("/emotions")
async def get_emotions(request: Request, limit: int = 30) -> dict:
    """Get emotional state history."""
    emotions = request.app.state.emotions
    current = emotions.get_current()
    history = emotions.get_history(limit=limit)
    return {"current": current, "history": history}


@router.get("/opinions")
async def get_opinions(request: Request, limit: int = 20) -> dict:
    """Get current opinions."""
    opinions = request.app.state.opinions
    current = opinions.get_current(limit=limit)
    return {"opinions": current}


@router.get("/memories")
async def get_memories(request: Request, limit: int = 20,
                       memory_type: str | None = None) -> dict:
    """Get recent memories."""
    memory = request.app.state.memory
    memories = memory.recall(memory_type=memory_type, limit=limit)
    return {"memories": memories}


@router.get("/diary")
async def get_diary(request: Request, limit: int = 30) -> dict:
    """Get diary entries."""
    rows = request.app.state.conn.execute(
        "SELECT * FROM diary ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"diary": [dict(r) for r in rows]}


@router.get("/evolution")
async def get_evolution(request: Request, limit: int = 20) -> dict:
    """Get evolution log."""
    evolution = request.app.state.evolution
    recent = evolution.get_recent(limit=limit)
    return {"evolution": recent}


@router.get("/relationships")
async def get_relationships(request: Request) -> dict:
    """Get all relationships with other Sentaras."""
    rows = request.app.state.conn.execute(
        "SELECT * FROM relationships ORDER BY last_seen_at DESC"
    ).fetchall()
    return {"relationships": [dict(r) for r in rows]}
