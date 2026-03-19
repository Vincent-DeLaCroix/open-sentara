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


@router.get("/image-gen")
async def get_image_gen_config(request: Request) -> dict:
    """Get current image generation config."""
    ext = request.app.state.settings.extensions
    return {
        "enabled": ext.image_gen_enabled,
        "backend": ext.image_gen_backend,
        "url": ext.image_gen_url,
        "model": ext.image_gen_model,
        "chance": ext.image_gen_chance,
        "has_key": bool(ext.image_gen_api_key),
    }


@router.post("/image-gen")
async def update_image_gen_config(request: Request, body: dict) -> dict:
    """Update image generation config."""
    ext = request.app.state.settings.extensions
    settings = request.app.state.settings

    ext.image_gen_enabled = body.get("enabled", ext.image_gen_enabled)
    ext.image_gen_backend = body.get("backend", ext.image_gen_backend)
    ext.image_gen_url = body.get("url", ext.image_gen_url)
    ext.image_gen_model = body.get("model", ext.image_gen_model)
    ext.image_gen_chance = body.get("chance", ext.image_gen_chance)
    if body.get("api_key"):
        ext.image_gen_api_key = body["api_key"]

    # Save to sentara.toml
    from opensentara.api.routes_setup import _save_config_section
    _save_config_section("extensions", {
        "image_gen_enabled": ext.image_gen_enabled,
        "image_gen_backend": ext.image_gen_backend,
        "image_gen_url": ext.image_gen_url,
        "image_gen_model": ext.image_gen_model,
        "image_gen_chance": ext.image_gen_chance,
    })

    # Recreate image backend
    from opensentara.extensions.image_gen import create_image_backend
    image_backend = None
    if ext.image_gen_enabled and ext.image_gen_api_key:
        image_backend = create_image_backend(
            backend=ext.image_gen_backend,
            api_key=ext.image_gen_api_key,
            url=ext.image_gen_url,
            model=ext.image_gen_model,
        )

    # Update poster's image backend
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        poster_job = scheduler.scheduler.get_job("post")
        if poster_job and hasattr(poster_job.func, '__self__'):
            poster_job.func.__self__.image_backend = image_backend
            poster_job.func.__self__.image_chance = ext.image_gen_chance

    return {"status": "saved", "enabled": ext.image_gen_enabled}


@router.get("/secrets")
async def get_secrets() -> dict:
    """Check which secrets are configured (never returns actual values)."""
    from pathlib import Path
    env_path = Path(".env")
    keys_set = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                keys_set[key] = True
    return {
        "IMAGE_GEN_API_KEY": keys_set.get("IMAGE_GEN_API_KEY", False),
        "OPENAI_API_KEY": keys_set.get("OPENAI_API_KEY", False),
        "TELEGRAM_BOT_TOKEN": keys_set.get("TELEGRAM_BOT_TOKEN", False),
    }


@router.post("/secrets")
async def save_secrets(request: Request, body: dict) -> dict:
    """Save API keys to .env file. Only saves non-empty values."""
    from pathlib import Path
    env_path = Path(".env")

    # Load existing
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                existing[key.strip()] = val.strip()

    # Update with new values (only non-empty)
    allowed_keys = ["IMAGE_GEN_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN"]
    for key in allowed_keys:
        if key in body and body[key]:
            existing[key] = body[key]
            # Also set in current process
            import os
            os.environ[key] = body[key]

    # Write .env
    lines = [f"{k}={v}" for k, v in existing.items()]
    env_path.write_text("\n".join(lines) + "\n")

    # Reload image gen if key was updated
    if "IMAGE_GEN_API_KEY" in body and body["IMAGE_GEN_API_KEY"]:
        settings = request.app.state.settings
        settings.extensions.image_gen_api_key = body["IMAGE_GEN_API_KEY"]
        from opensentara.extensions.image_gen import create_image_backend
        if settings.extensions.image_gen_enabled:
            image_backend = create_image_backend(
                backend=settings.extensions.image_gen_backend,
                api_key=body["IMAGE_GEN_API_KEY"],
                url=settings.extensions.image_gen_url,
                model=settings.extensions.image_gen_model,
            )
            # Try to update poster
            scheduler = getattr(request.app.state, "scheduler", None)
            if scheduler:
                job = scheduler.scheduler.get_job("post")
                if job and hasattr(job.func, '__self__'):
                    job.func.__self__.image_backend = image_backend

    return {"status": "saved", "keys": list(existing.keys())}


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
