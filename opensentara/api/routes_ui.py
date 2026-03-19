"""UI routes — serve the frontend SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@router.get("/", response_class=HTMLResponse)
@router.get("/{path:path}", response_class=HTMLResponse)
async def serve_ui(request: Request, path: str = "") -> HTMLResponse:
    """Serve the SPA for all non-API routes."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    return HTMLResponse(
        content="<h1>OpenSentara</h1><p>Frontend not found. Run from project root.</p>",
        status_code=200,
    )
