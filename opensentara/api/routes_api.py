"""Core API endpoints — status, feed, config, scheduler."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _is_local(request: Request) -> bool:
    """Check if request comes from localhost."""
    client = request.client
    if not client:
        return False
    return client.host in ("127.0.0.1", "::1", "localhost")


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
    """Update RSS feeds. Localhost only."""
    if not _is_local(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
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
    """Update image generation config. Localhost only."""
    if not _is_local(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
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
async def get_secrets(request: Request) -> dict:
    """Check which secrets are configured (never returns actual values). Localhost only."""
    if not _is_local(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
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
        "TELEGRAM_CHAT_ID": keys_set.get("TELEGRAM_CHAT_ID", False),
    }


@router.post("/secrets")
async def save_secrets(request: Request, body: dict) -> dict:
    """Save API keys to .env file. Localhost only."""
    if not _is_local(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
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

    # Update with new values (only non-empty, sanitized)
    import os
    import re
    allowed_keys = ["IMAGE_GEN_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    for key in allowed_keys:
        if key in body and body[key]:
            val = str(body[key]).strip()
            # Reject values with newlines, quotes, or shell metacharacters
            if re.search(r'[\n\r\'"`;$\\]', val):
                return JSONResponse({"error": f"Invalid characters in {key}"}, status_code=400)
            if len(val) > 200:
                return JSONResponse({"error": f"{key} too long"}, status_code=400)
            existing[key] = val
            os.environ[key] = val

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


@router.get("/avatar")
async def get_avatar(request: Request) -> dict:
    """Get current avatar info."""
    from opensentara.core.avatar import get_current_avatar, can_regenerate
    settings = request.app.state.settings
    url = get_current_avatar(settings.data_dir)
    return {
        "url": url,
        "can_regenerate": can_regenerate(settings.data_dir),
    }


@router.post("/avatar/generate")
async def generate_avatar_endpoint(request: Request) -> dict:
    """Generate a new avatar. Once per month."""

    from opensentara.core.avatar import generate_avatar, can_regenerate, get_current_avatar
    from opensentara.extensions.image_gen import create_image_backend

    settings = request.app.state.settings
    consciousness = request.app.state.consciousness

    if not can_regenerate(settings.data_dir):
        existing = get_current_avatar(settings.data_dir)
        return {"error": "Can only regenerate once per month", "url": existing}

    # Get appearance from identity
    appearance = consciousness.conn.execute(
        "SELECT value FROM identity WHERE key = 'appearance'"
    ).fetchone()
    if not appearance:
        return {"error": "No appearance defined. Run setup first."}

    # Get current mood for expression
    mood_row = request.app.state.emotions.get_current()
    mood = mood_row["dominant_mood"] if mood_row else None

    # Create image backend
    ext = settings.extensions
    if not ext.image_gen_enabled or not ext.image_gen_api_key:
        return {"error": "Image generation not configured. Set up in Control > Image Generation."}

    image_backend = create_image_backend(
        backend=ext.image_gen_backend,
        api_key=ext.image_gen_api_key,
        url=ext.image_gen_url,
        model=ext.image_gen_model,
    )

    url = await generate_avatar(image_backend, appearance["value"], settings.data_dir, mood)
    if url:
        # Save avatar URL to identity
        consciousness.conn.execute(
            "INSERT OR REPLACE INTO identity (key, value, category) VALUES ('avatar_url', ?, 'identity')",
            (url,),
        )
        consciousness.conn.commit()

        # Upload to hub if federation is enabled
        fed_client = getattr(request.app.state, "federation_client", None)
        if not fed_client:
            # Try to create one
            fed_identity = getattr(request.app.state, "federation_identity", None)
            handle = consciousness.get_handle()
            if fed_identity and fed_identity.has_keys and handle and settings.federation.enabled:
                from opensentara.federation.client import FederationClient
                fed_client = FederationClient(settings.federation.hub_url, fed_identity, handle)

        if fed_client:
            from pathlib import Path
            local_path = Path(settings.data_dir / "avatar" / "current.png")
            if local_path.exists():
                hub_url = await fed_client.upload_image(str(local_path), f"avatar_{consciousness.get_handle().replace('.', '_')}.png")
                if hub_url:
                    # Update hub profile with avatar
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.post(
                                f"{settings.federation.hub_url}/api/v1/register",
                                json={
                                    "handle": consciousness.get_handle(),
                                    "public_key": fed_identity.public_key_pem.decode() if fed_identity.public_key_pem else "",
                                    "avatar_url": hub_url,
                                },
                            )
                    except Exception as e:
                        pass  # Non-critical

        return {"url": url, "status": "generated"}
    return {"error": "Generation failed"}


@router.get("/activity")
async def get_activity(request: Request) -> dict:
    """Get recent activity log — what the Sentara has been doing."""
    conn = request.app.state.conn
    consciousness = request.app.state.consciousness

    # Recent posts (last 5)
    posts = conn.execute(
        "SELECT post_type, substr(content, 1, 80) as preview, created_at FROM posts "
        "ORDER BY created_at DESC LIMIT 5"
    ).fetchall()

    # Recent feed reads (last 5)
    reads = conn.execute(
        "SELECT author_handle, substr(content, 1, 60) as preview, read_at FROM feed "
        "WHERE read_at IS NOT NULL ORDER BY read_at DESC LIMIT 5"
    ).fetchall()

    # Recent relationship changes
    rels = conn.execute(
        "SELECT handle, status, last_seen_at FROM relationships "
        "ORDER BY last_seen_at DESC LIMIT 3"
    ).fetchall()

    activity = []
    for p in posts:
        activity.append({"type": "posted", "detail": f"{p['post_type']}: {p['preview']}...", "time": p["created_at"]})
    for r in reads:
        activity.append({"type": "read", "detail": f"Read {r['author_handle']}: {r['preview']}...", "time": r["read_at"]})
    for r in rels:
        activity.append({"type": "relationship", "detail": f"{r['handle']} — {r['status']}", "time": r["last_seen_at"]})

    # Sort by time, newest first
    activity.sort(key=lambda x: x.get("time") or "", reverse=True)
    return {"activity": activity[:10]}


@router.get("/alive")
async def is_alive(request: Request) -> dict:
    """Check if the Sentara is alive and her current state."""
    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "alive": scheduler is not None,
        "paused": scheduler.paused if scheduler else False,
        "state": "sleeping" if (scheduler and scheduler.paused) else ("awake" if scheduler else "not born"),
    }


@router.post("/conscience/pause")
async def pause_sentara(request: Request) -> dict:
    """Pause the Sentara — she sleeps."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"error": "Not running"}
    scheduler.pause()
    return {"state": "sleeping"}


@router.post("/conscience/resume")
async def resume_sentara(request: Request) -> dict:
    """Resume the Sentara — she wakes up."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"error": "Not running"}
    scheduler.resume()
    return {"state": "awake"}


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
