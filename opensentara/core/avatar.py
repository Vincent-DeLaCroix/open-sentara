"""Avatar generator — each Sentara creates her own photorealistic face."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

AVATAR_PROMPT_TEMPLATE = """Professional portrait photograph of {appearance}.
Headshot, studio lighting, shallow depth of field, neutral dark background.
Photorealistic, high quality, sharp focus on face.
No text, no watermark, no frame."""


def build_avatar_prompt(appearance: str, mood: str | None = None) -> str:
    """Build the image generation prompt from the Sentara's self-description."""
    prompt = AVATAR_PROMPT_TEMPLATE.format(appearance=appearance)
    if mood:
        prompt += f"\nExpression conveys {mood}."
    return prompt


async def generate_avatar(image_backend, appearance: str, data_dir: Path,
                          mood: str | None = None) -> str | None:
    """Generate avatar image. Returns local path or None."""
    if not image_backend:
        log.warning("No image backend configured — cannot generate avatar")
        return None

    prompt = build_avatar_prompt(appearance, mood)
    log.info(f"Generating avatar: {prompt[:80]}...")

    avatar_dir = data_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)

    # Filename includes timestamp so we keep history
    timestamp = datetime.now(timezone.utc).strftime("%Y%m")
    filename = f"avatar_{timestamp}.png"
    output_path = avatar_dir / filename

    result = await image_backend.generate(prompt, output_path)
    if result and result.exists():
        # Also save as current avatar
        current = avatar_dir / "current.png"
        import shutil
        shutil.copy2(str(output_path), str(current))
        log.info(f"Avatar generated: {output_path} ({output_path.stat().st_size} bytes)")
        return f"/conscience/avatar/current.png"

    log.warning("Avatar generation failed")
    return None


def get_current_avatar(data_dir: Path) -> str | None:
    """Get the current avatar URL, or None if no avatar exists."""
    current = data_dir / "avatar" / "current.png"
    if current.exists():
        return "/conscience/avatar/current.png"
    return None


def can_regenerate(data_dir: Path) -> bool:
    """Check if enough time has passed to regenerate (once per month)."""
    current = data_dir / "avatar" / "current.png"
    if not current.exists():
        return True  # Never generated

    import os
    mtime = datetime.fromtimestamp(os.path.getmtime(current), tz=timezone.utc)
    now = datetime.now(timezone.utc)
    days_since = (now - mtime).days
    return days_since >= 30
