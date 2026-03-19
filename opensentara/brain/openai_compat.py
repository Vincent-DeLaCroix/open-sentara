"""OpenAI-compatible brain backend (works with any /v1/chat/completions endpoint)."""

from __future__ import annotations

import httpx
from .base import BrainBackend


class OpenAICompatBrain(BrainBackend):
    def __init__(self, url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4o-mini", api_key: str = ""):
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key

    async def think(self, prompt: str, system: str | None = None,
                    temperature: float = 0.7) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def is_available(self) -> bool:
        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.url}/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False
