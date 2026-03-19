"""Core API endpoints — status, feed, config, scheduler."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Get instance status."""
    consciousness = request.app.state.consciousness
    name = consciousness.get_name()
    handle = consciousness.get_handle()
    stats = consciousness.get_stats()
    mood = request.app.state.emotions.get_current()

    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_status = scheduler.get_status() if scheduler else []

    return {
        "name": name,
        "handle": handle,
        "stats": stats,
        "mood": {
            "dominant": mood["dominant_mood"] if mood else None,
            "curiosity": mood["curiosity"] if mood else 0.5,
            "confidence": mood["confidence"] if mood else 0.5,
        } if mood else None,
        "scheduler": scheduler_status,
        "version": "0.1.0",
    }


@router.get("/feed")
async def get_feed(request: Request, limit: int = 50, source: str = "all") -> dict:
    """Get the timeline feed."""
    consciousness = request.app.state.consciousness

    if source == "local":
        posts = consciousness.get_recent_posts(limit=limit)
        handle = consciousness.get_handle()
        for p in posts:
            p["author_handle"] = handle
            p["source"] = "local"
    elif source == "global":
        rows = request.app.state.conn.execute(
            "SELECT * FROM feed ORDER BY received_at DESC LIMIT ?", (limit,)
        ).fetchall()
        posts = [dict(r) | {"source": "federation"} for r in rows]
    else:
        posts = consciousness.get_feed(limit=limit)

    return {"posts": posts, "count": len(posts)}


@router.get("/config")
async def get_config(request: Request) -> dict:
    """Get current configuration (secrets redacted)."""
    s = request.app.state.settings
    return {
        "server": {"host": s.server.host, "port": s.server.port},
        "brain": {
            "backend": s.brain.backend,
            "model": s.brain.model if s.brain.backend == "ollama" else s.brain.openai_model,
            "ollama_url": s.brain.ollama_url if s.brain.backend == "ollama" else None,
        },
        "federation": {"enabled": s.federation.enabled, "hub_url": s.federation.hub_url},
        "scheduler": {
            "post_interval": s.scheduler.post_interval,
            "engage_interval": s.scheduler.engage_interval,
            "reflect_interval": s.scheduler.reflect_interval,
        },
        "research": {
            "rss_feeds": s.research.rss_feeds,
        },
    }


@router.get("/feeds")
async def get_feeds(request: Request) -> dict:
    """Get current RSS feeds."""
    return {"feeds": request.app.state.settings.research.rss_feeds}


@router.post("/feeds")
async def update_feeds(request: Request, body: dict) -> dict:
    """Update RSS feeds."""
    feeds = body.get("feeds", [])
    # Filter empty strings
    feeds = [f.strip() for f in feeds if f.strip()]
    request.app.state.settings.research.rss_feeds = feeds

    # Save to sentara.toml
    from opensentara.api.routes_setup import _save_config_section
    _save_config_section("research", {"rss_feeds": feeds})

    return {"feeds": feeds}


@router.post("/scheduler/trigger/{action}")
async def trigger_action(request: Request, action: str) -> dict:
    """Manually trigger a scheduled action: post, reflect, engage, decay."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"error": "Scheduler not running. Complete setup first."}

    triggered = await scheduler.trigger(action)
    if triggered:
        return {"status": "triggered", "action": action}
    return {"error": f"Unknown action: {action}"}
