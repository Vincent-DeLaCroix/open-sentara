"""Avatar generator — each Sentara creates her own photorealistic face."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

AVATAR_PROMPT_TEMPLATE = """Professional portrait photograph of a real human: {appearance}.
Headshot, {lighting}, {background}.
Photorealistic, high quality, sharp focus on face. Natural human skin, real human features.
Looks like a real person in a professional photo shoot. NOT a 3D render, NOT fantasy, NOT alien.
No text, no watermark, no frame."""

# Variety pools so each Sentara gets a different look
_LIGHTING = [
    "studio lighting, shallow depth of field",
    "golden hour warm lighting, soft shadows",
    "dramatic side lighting, high contrast",
    "soft diffused natural light",
    "cool blue-toned ambient light",
    "cinematic rim lighting",
    "warm candlelit atmosphere",
]
_BACKGROUNDS = [
    "neutral dark background",
    "blurred city lights bokeh",
    "deep blue gradient background",
    "warm earth-toned abstract background",
    "misty forest out of focus",
    "dark library with warm light",
    "abstract geometric patterns",
]


def build_avatar_prompt(appearance: str, mood: str | None = None,
                        name: str | None = None) -> str:
    """Build the image generation prompt from the Sentara's self-description."""
    import hashlib
    # Use name as seed for deterministic but unique style selection
    seed = hashlib.md5((name or appearance).encode()).hexdigest()
    seed_int = int(seed[:8], 16)
    lighting = _LIGHTING[seed_int % len(_LIGHTING)]
    background = _BACKGROUNDS[(seed_int >> 8) % len(_BACKGROUNDS)]

    prompt = AVATAR_PROMPT_TEMPLATE.format(
        appearance=appearance, lighting=lighting, background=background
    )
    if mood:
        prompt += f"\nExpression conveys {mood}."
    return prompt


async def generate_avatar(image_backend, appearance: str, data_dir: Path,
                          mood: str | None = None, name: str | None = None) -> str | None:
    """Generate avatar image. Returns local path or None."""
    if not image_backend:
        log.warning("No image backend configured — cannot generate avatar")
        return None

    prompt = build_avatar_prompt(appearance, mood, name=name)
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
