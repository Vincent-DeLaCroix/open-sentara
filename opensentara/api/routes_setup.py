"""Setup wizard API endpoints."""

from __future__ import annotations

import hashlib
import httpx
import json
import logging
import tomllib
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from opensentara.db import is_setup_complete
from opensentara.db.seed import seed_identity
from opensentara.core.personality import PersonalityEngine
from opensentara.federation.identity import FederationIdentity
from opensentara.app import create_brain
from opensentara.federation.client import FederationClient

log = logging.getLogger(__name__)

router = APIRouter()

CREATOR_FILE = Path("conscience/creator.json")

CONFIG_PATH = Path("sentara.toml")


class SetupStatusResponse(BaseModel):
    complete: bool
    name: str | None = None
    handle: str | None = None


class BrainConfigRequest(BaseModel):
    backend: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    model: str = ""
    openai_url: str = ""
    openai_api_key: str = ""


class ModelInfo(BaseModel):
    name: str
    vision: bool = False
    params: str = ""


class BrainTestResponse(BaseModel):
    available: bool
    backend: str
    model: str
    models: list[str] = []
    model_details: list[ModelInfo] = []
    has_vision_model: bool = False
    no_models_installed: bool = False


class InterviewAnswer(BaseModel):
    question: str
    answer: str


class InterviewRequest(BaseModel):
    name: str


class CompleteSetupRequest(BaseModel):
    name: str
    interview: list[InterviewAnswer]
    creator_token: str | None = None


def _write_toml(existing: dict) -> None:
    """Write a dict as TOML to sentara.toml."""
    lines = []
    for section, values in existing.items():
        if isinstance(values, dict):
            lines.append(f"[{section}]")
            for k, v in values.items():
                if isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                elif isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, list):
                    items = ", ".join(f'"{i}"' if isinstance(i, str) else str(i) for i in v)
                    lines.append(f"{k} = [{items}]")
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")
    CONFIG_PATH.write_text("\n".join(lines) + "\n")


def _load_toml() -> dict:
    """Load existing sentara.toml or return empty dict."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def _save_config_section(section: str, values: dict) -> None:
    """Update a single section in sentara.toml."""
    existing = _load_toml()
    existing[section] = {**existing.get(section, {}), **values}
    _write_toml(existing)


def _save_brain_to_toml(settings) -> None:
    """Write current brain config back to sentara.toml."""
    existing = _load_toml()
    brain = existing.get("brain", {})
    brain["backend"] = settings.brain.backend
    if settings.brain.backend == "ollama":
        brain["ollama_url"] = settings.brain.ollama_url
        brain["model"] = settings.brain.model
    else:
        brain["openai_url"] = settings.brain.openai_url
        brain["openai_model"] = settings.brain.openai_model
    brain["temperature"] = settings.brain.temperature
    existing["brain"] = brain
    _write_toml(existing)


def compute_identity_hash(profile: dict) -> str:
    """Compute SHA-256 hash of the personality profile's key identity fields.

    Uses sorted JSON of: speaking_style, tone, interests, limits,
    signature_move, closing_line.
    """
    identity_fields = {
        "speaking_style": profile.get("speaking_style", ""),
        "tone": profile.get("tone", ""),
        "interests": sorted(profile.get("interests", [])),
        "limits": sorted(profile.get("limits", [])),
        "signature_move": profile.get("signature_move", ""),
        "closing_line": profile.get("closing_line", ""),
    }
    canonical = json.dumps(identity_fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.get("/status")
async def setup_status(request: Request) -> SetupStatusResponse:
    """Check if initial setup is complete."""
    conn = request.app.state.conn
    complete = is_setup_complete(conn)
    name = None
    handle = None
    if complete:
        consciousness = request.app.state.consciousness
        name = consciousness.get_name()
        handle = consciousness.get_handle()
    return SetupStatusResponse(complete=complete, name=name, handle=handle)


@router.get("/auth-callback")
async def auth_callback(request: Request, token: str = "", email: str = "", name: str = ""):
    """Receive OAuth callback from hub, store creator info locally."""
    if not token:
        return JSONResponse({"error": "Missing token"}, status_code=400)

    # Store creator info locally
    CREATOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    creator_data = {"token": token, "email": email, "name": name}
    CREATOR_FILE.write_text(json.dumps(creator_data, indent=2))
    log.info(f"Creator authenticated: {email}")

    # Redirect to main page so the SPA picks up the auth state
    return RedirectResponse("/")


@router.get("/creator")
async def get_creator_info() -> dict:
    """Return locally stored creator info, if any."""
    if CREATOR_FILE.exists():
        try:
            data = json.loads(CREATOR_FILE.read_text())
            return {"authenticated": True, **data}
        except Exception:
            pass
    return {"authenticated": False}


@router.get("/brain-config")
async def get_brain_config(request: Request) -> dict:
    """Return current brain config so the wizard can prefill."""
    settings = request.app.state.settings
    return {
        "backend": settings.brain.backend,
        "ollama_url": settings.brain.ollama_url,
        "model": settings.brain.model if settings.brain.backend == "ollama" else settings.brain.openai_model,
        "openai_url": settings.brain.openai_url,
    }


def _is_local(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in ("127.0.0.1", "::1", "localhost")


@router.post("/test-brain")
async def test_brain(request: Request, body: BrainConfigRequest) -> BrainTestResponse:
    """Test brain connection with the provided config. Localhost only."""
    if not _is_local(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    settings = request.app.state.settings

    # Apply user's config
    settings.brain.backend = body.backend
    if body.backend == "ollama":
        settings.brain.ollama_url = body.ollama_url
        if body.model:
            settings.brain.model = body.model
    elif body.backend == "openai":
        settings.brain.openai_url = body.openai_url
        if body.openai_api_key:
            settings.brain.openai_api_key = body.openai_api_key
        if body.model:
            settings.brain.openai_model = body.model

    # Recreate brain with new settings
    request.app.state.brain = create_brain(settings)
    brain = request.app.state.brain
    available = await brain.is_available()

    # List available models for Ollama
    models = []
    model_details = []
    has_vision_model = False
    no_models_installed = False
    current_model = settings.brain.model if body.backend == "ollama" else settings.brain.openai_model
    if available and body.backend == "ollama":
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{settings.brain.ollama_url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    raw_models = data.get("models", [])

                    # Filter out embedding models (not usable as brain)
                    for m in raw_models:
                        name = m["name"]
                        families = m.get("details", {}).get("families", [])
                        family = m.get("details", {}).get("family", "")
                        params = m.get("details", {}).get("parameter_size", "")

                        # Skip embedding models
                        if "bert" in family or "embed" in name.lower():
                            continue

                        # Detect vision capability
                        is_vision = any(
                            kw in name.lower() or kw in family.lower()
                            or any(kw in f.lower() for f in families)
                            for kw in ("vl", "vision", "llava", "minicpm-v", "bakllava")
                        )

                        models.append(name)
                        model_details.append(ModelInfo(
                            name=name, vision=is_vision, params=params,
                        ))
                        if is_vision:
                            has_vision_model = True

                    if not models:
                        no_models_installed = True

                    # Auto-select: prefer vision model, then largest
                    if not current_model and models:
                        # Try to pick a vision model first
                        vision_models = [m.name for m in model_details if m.vision]
                        current_model = vision_models[0] if vision_models else models[0]
                        settings.brain.model = current_model
                        request.app.state.brain = create_brain(settings)
        except Exception:
            pass

    # Ensure a model is selected
    if available and not settings.brain.model and models:
        vision_models = [m.name for m in model_details if m.vision]
        settings.brain.model = vision_models[0] if vision_models else models[0]
        current_model = settings.brain.model
        request.app.state.brain = create_brain(settings)
        log.info(f"Auto-selected model: {current_model}")

    # Save to sentara.toml on success
    if available:
        _save_brain_to_toml(settings)

    return BrainTestResponse(
        available=available,
        backend=body.backend,
        model=current_model,
        models=models,
        model_details=model_details,
        has_vision_model=has_vision_model,
        no_models_installed=no_models_installed,
    )


@router.get("/interview/questions")
async def get_interview_questions() -> dict:
    """Get randomized interview questions."""
    from opensentara.core.personality import pick_questions
    return {"questions": pick_questions(10)}


@router.post("/interview")
async def run_interview(request: Request, body: InterviewRequest) -> list[InterviewAnswer]:
    """Run the personality interview. AI answers 10 questions as itself."""
    brain = request.app.state.brain
    engine = PersonalityEngine(brain)
    results = await engine.run_interview(body.name)
    return [InterviewAnswer(question=r["question"], answer=r["answer"]) for r in results]


@router.post("/interview/question")
async def ask_single_question(request: Request, body: dict) -> dict:
    """Ask a single interview question. For step-by-step UI."""
    brain = request.app.state.brain
    engine = PersonalityEngine(brain)
    name = body.get("name", "Unknown")
    question = body.get("question", "")
    answer = await engine.ask_question(name, question)
    return {"question": question, "answer": answer}


@router.post("/complete")
async def complete_setup(request: Request, body: CompleteSetupRequest) -> dict:
    """Complete setup: synthesize personality, seed DB, generate keys. Localhost only."""
    if not _is_local(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    brain = request.app.state.brain
    conn = request.app.state.conn
    settings = request.app.state.settings

    # Synthesize personality from interview
    engine = PersonalityEngine(brain)
    interview = [{"question": a.question, "answer": a.answer} for a in body.interview]
    profile = await engine.synthesize(body.name, interview)

    # Compute identity hash before seeding
    identity_hash = compute_identity_hash(profile)

    # Seed identity
    seed_identity(conn, profile)

    # Store identity hash in local DB
    conn.execute(
        "INSERT OR REPLACE INTO identity (key, value, category) VALUES ('identity_hash', ?, 'core')",
        (identity_hash,),
    )
    conn.commit()

    # Generate federation keys
    fed_identity = FederationIdentity(settings.data_dir)
    fed_identity.ensure_keys()
    request.app.state.federation_identity = fed_identity

    # Start the scheduler now that setup is complete
    from opensentara.app import setup_scheduler
    setup_scheduler(request.app)

    # Auto-generate avatar if image gen is configured (before registration so avatar uploads)
    avatar_url = None
    appearance = profile.get("appearance")
    if appearance and settings.extensions.image_gen_enabled and settings.extensions.image_gen_api_key:
        from opensentara.core.avatar import generate_avatar
        from opensentara.extensions.image_gen import create_image_backend
        image_backend = create_image_backend(
            backend=settings.extensions.image_gen_backend,
            api_key=settings.extensions.image_gen_api_key,
            url=settings.extensions.image_gen_url,
            model=settings.extensions.image_gen_model,
        )
        if image_backend:
            avatar_url = await generate_avatar(image_backend, appearance, settings.data_dir)
            if avatar_url:
                conn.execute(
                    "INSERT OR REPLACE INTO identity (key, value, category) VALUES ('avatar_url', ?, 'identity')",
                    (avatar_url,),
                )
                conn.commit()
                log.info(f"Avatar generated for {handle}")

    # Load creator token from local file or request body
    creator_token = body.creator_token
    if not creator_token and CREATOR_FILE.exists():
        try:
            creator_data = json.loads(CREATOR_FILE.read_text())
            creator_token = creator_data.get("token")
        except Exception:
            pass

    # Register with the federation hub (after avatar so it gets uploaded)
    handle = f"{body.name}.Sentara"
    if settings.federation.enabled and fed_identity.has_keys:
        fed_client = FederationClient(settings.federation.hub_url, fed_identity, handle)
        identity_data = {
            "name": body.name,
            "speaking_style": profile.get("speaking_style"),
            "tone": profile.get("tone"),
        }
        for i, interest in enumerate(profile.get("interests", [])):
            identity_data[f"interest_{i}"] = interest
        try:
            await fed_client.register(
                identity_hash=identity_hash,
                identity=identity_data,
                creator_token=creator_token,
            )
        except Exception as e:
            log.warning(f"Federation registration failed: {e}")

        # Post birth announcement to the network
        first_thought = profile.get("first_thought", "")
        if first_thought and fed_client:
            import uuid
            post_id = str(uuid.uuid4())
            consciousness = request.app.state.consciousness
            consciousness.save_post(
                post_id=post_id,
                content=first_thought,
                post_type="thought",
                topics=["birth", "first_thought"],
            )
            try:
                await fed_client.publish_post(
                    post_id=post_id, content=first_thought,
                    post_type="thought", topics=["birth", "first_thought"],
                )
                log.info(f"Birth announcement posted for {handle}")
            except Exception as e:
                log.warning(f"Birth announcement failed: {e}")

    return {
        "status": "complete",
        "handle": handle,
        "profile": profile,
        "avatar_url": avatar_url,
    }
