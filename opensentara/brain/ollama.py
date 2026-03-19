"""Ollama brain backend."""

from __future__ import annotations

import httpx
from .base import BrainBackend


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

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
