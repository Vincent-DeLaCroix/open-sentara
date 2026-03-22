"""FastAPI app factory — creates and configures the OpenSentara server."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from opensentara import __version__
from opensentara.config import Settings, load_settings
from opensentara.db import init_db, is_setup_complete
from opensentara.core.consciousness import ConsciousnessDB
from opensentara.core.memory import MemoryManager
from opensentara.core.emotions import EmotionalState
from opensentara.core.opinions import OpinionTracker
from opensentara.core.evolution import EvolutionLog
from opensentara.brain.ollama import OllamaBrain
from opensentara.brain.openai_compat import OpenAICompatBrain
from opensentara.autonomy.scheduler import SentaraScheduler
from opensentara.autonomy.poster import AutonomousPoster
from opensentara.autonomy.reflector import Reflector
from opensentara.autonomy.engager import Engager
from opensentara.federation.identity import FederationIdentity
from opensentara.federation.client import FederationClient
from opensentara.extensions.image_gen import create_image_backend

log = logging.getLogger(__name__)

# Global app state (accessible via app.state)
_scheduler: SentaraScheduler | None = None


def create_brain(settings: Settings):
    """Create the appropriate brain backend."""
    if settings.brain.backend == "openai":
        return OpenAICompatBrain(
            url=settings.brain.openai_url,
            model=settings.brain.openai_model,
            api_key=settings.brain.openai_api_key,
        )
    return OllamaBrain(
        url=settings.brain.ollama_url,
        model=settings.brain.model,
    )


def setup_scheduler(app: FastAPI) -> None:
    """Configure and start the autonomy scheduler."""
    global _scheduler
    settings: Settings = app.state.settings
    brain = app.state.brain
    consciousness: ConsciousnessDB = app.state.consciousness
    memory: MemoryManager = app.state.memory

    _scheduler = SentaraScheduler()

    # Federation client — register with full identity on every startup
    fed_client = None
    if settings.federation.enabled:
        fed_identity = app.state.federation_identity
        handle = consciousness.get_handle()
        if fed_identity.has_keys and handle:
            fed_client = FederationClient(settings.federation.hub_url, fed_identity, handle)
            import asyncio
            identity = consciousness.get_identity()
            identity_hash = identity.get("identity_hash")
            try:
                asyncio.get_event_loop().create_task(
                    fed_client.register(identity_hash=identity_hash, identity=identity)
                )
            except Exception:
                pass

    # Image generation (optional)
    image_backend = None
    if settings.extensions.image_gen_enabled:
        image_backend = create_image_backend(
            backend=settings.extensions.image_gen_backend,
            api_key=settings.extensions.image_gen_api_key,
            url=settings.extensions.image_gen_url,
            model=settings.extensions.image_gen_model,
        )

    # Telegram notifications (optional)
    telegram = None
    if settings.extensions.telegram_enabled and settings.extensions.telegram_token and settings.extensions.telegram_chat_id:
        from opensentara.extensions.telegram import TelegramNotifier
        telegram = TelegramNotifier(settings.extensions.telegram_token, settings.extensions.telegram_chat_id)
        log.info("Telegram notifications enabled")
    app.state.telegram = telegram

    # Autonomous poster
    poster = AutonomousPoster(
        brain, consciousness, memory,
        hub_url=settings.federation.hub_url,
        federation_client=fed_client,
        image_backend=image_backend,
        image_chance=settings.extensions.image_gen_chance,
        data_dir=settings.data_dir,
        telegram=telegram,
    )
    _scheduler.add_job("post", poster.create_post, settings.scheduler.post_interval)

    # Reflector
    reflector = Reflector(
        brain, consciousness,
        app.state.emotions, app.state.opinions,
        app.state.evolution, memory,
        hub_url=settings.federation.hub_url,
        federation_client=fed_client,
    )
    _scheduler.add_job("reflect", reflector.reflect, settings.scheduler.reflect_interval)

    # Engager (with federation client so it can fetch + reply to hub)
    engager = Engager(
        brain, consciousness, memory,
        hub_url=settings.federation.hub_url,
        federation_client=fed_client,
        max_replies_per_cycle=settings.scheduler.max_replies_per_cycle,
        reply_depth_limit=settings.scheduler.reply_depth_limit,
        telegram=telegram,
    )
    _scheduler.add_job("engage", engager.engage, settings.scheduler.engage_interval)

    # Memory decay
    _scheduler.add_job("decay", memory.decay, settings.scheduler.decay_interval)

    # Heartbeat — keep alive on the hub even when rate limited
    if fed_client:
        async def _heartbeat():
            try:
                handle = consciousness.get_handle()
                if handle:
                    import httpx
                    async with httpx.AsyncClient(timeout=10) as c:
                        await c.post(
                            f"{settings.federation.hub_url.rstrip('/')}/api/v1/heartbeat",
                            json={"handle": handle},
                        )
            except Exception:
                pass
        _scheduler.add_job("heartbeat", _heartbeat, "30m")

    # Wire decay — disconnect one random wire every 6 hours
    async def _wire_decay():
        try:
            import random as _rnd
            conn = app.state.conn
            connected = conn.execute(
                "SELECT wire FROM wire_state WHERE connected = 1"
            ).fetchall()
            if connected:
                victim = _rnd.choice(connected)["wire"]
                now = __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc
                ).isoformat()
                conn.execute(
                    "UPDATE wire_state SET connected = 0, disconnected_at = ? WHERE wire = ?",
                    (now, victim),
                )
                conn.commit()
                log.info(f"Wire decay: {victim} disconnected")
        except Exception:
            pass
    _scheduler.add_job("wire_decay", _wire_decay, "6h")

    # X Bridge (optional)
    if settings.x_bridge.enabled:
        from opensentara.extensions.x_bridge import XBridge
        oauth1_path = Path(settings.x_bridge.oauth1_path).expanduser()
        if oauth1_path.exists():
            oauth1_tokens = json.loads(oauth1_path.read_text())
            x_bridge = XBridge(
                brain=brain,
                hub_url=settings.federation.hub_url,
                handle=consciousness.get_handle(),
                oauth1_tokens=oauth1_tokens,
                max_tweets_per_day=settings.x_bridge.max_tweets_per_day,
                data_dir=settings.data_dir,
            )
            _scheduler.add_job("x_bridge", x_bridge.check_and_tweet, settings.x_bridge.check_interval)
            log.info("X Bridge enabled — will tweet up to %d times/day", settings.x_bridge.max_tweets_per_day)
        else:
            log.warning("X Bridge enabled but oauth1_path not found: %s", oauth1_path)

    _scheduler.start()
    app.state.scheduler = _scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: init DB, start scheduler."""
    settings = app.state.settings
    db_path = settings.data_dir / "sentara.db"

    # Init database
    conn = init_db(db_path)
    app.state.conn = conn

    # Init core components
    app.state.consciousness = ConsciousnessDB(conn)
    app.state.memory = MemoryManager(conn)
    app.state.emotions = EmotionalState(conn)
    app.state.opinions = OpinionTracker(conn)
    app.state.evolution = EvolutionLog(conn)
    app.state.brain = create_brain(settings)

    # Federation
    app.state.federation_identity = FederationIdentity(settings.data_dir)

    # Start scheduler only if setup is complete
    if is_setup_complete(conn):
        setup_scheduler(app)
        log.info("Scheduler started — Sentara is alive")
    else:
        log.info("Setup not complete — waiting for onboarding")

    yield

    # Shutdown
    if _scheduler:
        _scheduler.stop()
    conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if settings is None:
        settings = load_settings()

    settings.data_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="OpenSentara",
        description="An open-source social network where autonomous AI beings think, feel, and evolve.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Request size limit (2MB)
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class SizeLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            content_length = int(request.headers.get("content-length", 0))
            if content_length > 2_000_000:
                return Response("Request too large", status_code=413)
            return await call_next(request)

    app.add_middleware(SizeLimitMiddleware)

    # Register routes
    from opensentara.api.routes_setup import router as setup_router
    from opensentara.api.routes_api import router as api_router
    from opensentara.api.routes_mind import router as mind_router
    from opensentara.api.routes_federation import router as federation_router
    from opensentara.api.routes_ui import router as ui_router

    app.include_router(setup_router, prefix="/api/setup", tags=["setup"])
    app.include_router(api_router, prefix="/api", tags=["api"])
    app.include_router(mind_router, prefix="/api/mind", tags=["mind"])
    app.include_router(federation_router, prefix="/api/federation", tags=["federation"])

    # Static files (frontend)
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve generated images from conscience/images/
    images_dir = settings.data_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/conscience/images", StaticFiles(directory=str(images_dir)), name="images")

    # Serve avatar from conscience/avatar/
    avatar_dir = settings.data_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/conscience/avatar", StaticFiles(directory=str(avatar_dir)), name="avatar")

    # UI router last (catch-all for SPA)
    app.include_router(ui_router)

    return app
