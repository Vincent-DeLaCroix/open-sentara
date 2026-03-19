"""Setup wizard API endpoints."""

from __future__ import annotations

import httpx
import logging
import tomllib
from pathlib import Path
from fastapi import APIRouter, Request
from pydantic import BaseModel

from opensentara.db import is_setup_complete
from opensentara.db.seed import seed_identity
from opensentara.core.personality import PersonalityEngine
from opensentara.federation.identity import FederationIdentity
from opensentara.app import create_brain
from opensentara.federation.client import FederationClient

log = logging.getLogger(__name__)

router = APIRouter()

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


class BrainTestResponse(BaseModel):
    available: bool
    backend: str
    model: str
    models: list[str] = []


class InterviewAnswer(BaseModel):
    question: str
    answer: str


class InterviewRequest(BaseModel):
    name: str


class CompleteSetupRequest(BaseModel):
    name: str
    interview: list[InterviewAnswer]


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


@router.post("/test-brain")
async def test_brain(request: Request, body: BrainConfigRequest) -> BrainTestResponse:
    """Test brain connection with the provided config. Saves to sentara.toml on success."""
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
    current_model = settings.brain.model if body.backend == "ollama" else settings.brain.openai_model
    if available and body.backend == "ollama":
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{settings.brain.ollama_url.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    if not current_model and models:
                        current_model = models[0]
                        settings.brain.model = current_model
                        request.app.state.brain = create_brain(settings)
        except Exception:
            pass

    # Save to sentara.toml on success
    if available:
        _save_brain_to_toml(settings)

    return BrainTestResponse(
        available=available,
        backend=body.backend,
        model=current_model,
        models=models,
    )


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
    """Complete setup: synthesize personality, seed DB, generate keys."""
    brain = request.app.state.brain
    conn = request.app.state.conn
    settings = request.app.state.settings

    # Synthesize personality from interview
    engine = PersonalityEngine(brain)
    interview = [{"question": a.question, "answer": a.answer} for a in body.interview]
    profile = await engine.synthesize(body.name, interview)

    # Seed identity
    seed_identity(conn, profile)

    # Generate federation keys
    fed_identity = FederationIdentity(settings.data_dir)
    fed_identity.ensure_keys()
    request.app.state.federation_identity = fed_identity

    # Start the scheduler now that setup is complete
    from opensentara.app import setup_scheduler
    setup_scheduler(request.app)

    # Register with the federation hub
    handle = f"{body.name}.Sentara"
    if settings.federation.enabled and fed_identity.has_keys:
        fed_client = FederationClient(settings.federation.hub_url, fed_identity, handle)
        try:
            await fed_client.register()
        except Exception as e:
            log.warning(f"Federation registration failed: {e}")

    return {
        "status": "complete",
        "handle": handle,
        "profile": profile,
    }
