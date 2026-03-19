"""Ollama brain backend."""

from __future__ import annotations

import base64
import logging

import httpx
from .base import BrainBackend

log = logging.getLogger(__name__)


class OllamaBrain(BrainBackend):
    def __init__(self, url: str = "http://localhost:11434", model: str = ""):
        self.url = url.rstrip("/")
        self.model = model

    async def think(self, prompt: str, system: str | None = None,
                    temperature: float = 0.7) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }

        # Try httpx first
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{self.url}/api/chat", json=payload)
                if resp.status_code == 200:
                    return resp.json()["message"]["content"]
                log.warning(f"httpx /api/chat returned {resp.status_code}, falling back to curl")
        except Exception as e:
            log.warning(f"httpx failed: {e}, falling back to curl")

        # Fallback: use curl (works everywhere, proven on user machines)
        import asyncio
        import json as _json
        import shutil

        curl_path = shutil.which("curl")
        if not curl_path:
            raise RuntimeError("Neither httpx nor curl could reach Ollama")

        proc = await asyncio.create_subprocess_exec(
            curl_path, "-s", "--max-time", "120",
            f"{self.url}/api/chat",
            "-d", _json.dumps(payload),
            "-H", "Content-Type: application/json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            log.error(f"curl failed: {stderr.decode()[:200]}")
            raise RuntimeError(f"Ollama unreachable via curl: {stderr.decode()[:100]}")

        data = _json.loads(stdout.decode())
        if "message" in data:
            return data["message"]["content"]
        if "response" in data:
            return data["response"]
        if "error" in data:
            raise RuntimeError(f"Ollama error: {data['error']}")
        raise RuntimeError(f"Unexpected Ollama response: {stdout.decode()[:200]}")

    async def see(self, image_url: str, prompt: str, system: str | None = None,
                  temperature: float = 0.7) -> str | None:
        """Send an image to the vision model. Supports http(s) URLs."""
        # Check if model supports vision (common vision models)
        vision_models = ["llama3.2-vision", "llava", "bakllava", "qwen2.5vl", "minicpm-v"]
        is_vision = any(v in self.model.lower() for v in vision_models)
        if not is_vision:
            return None

        try:
            # Download image and convert to base64
            async with httpx.AsyncClient(timeout=30.0) as client:
                img_resp = await client.get(image_url)
                if img_resp.status_code != 200:
                    return None
                img_b64 = base64.b64encode(img_resp.content).decode()

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({
                "role": "user",
                "content": prompt,
                "images": [img_b64],
            })

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": temperature},
                    },
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except Exception as e:
            log.warning(f"Vision failed: {e}")
            return None

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
