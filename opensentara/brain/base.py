"""Abstract brain backend."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BrainBackend(ABC):
    """Interface for AI backends."""

    @abstractmethod
    async def think(self, prompt: str, system: str | None = None,
                    temperature: float = 0.7) -> str:
        """Send a prompt to the AI and return the response text."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the backend is reachable."""
        ...
