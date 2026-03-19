"""WebSocket manager for live feed updates."""

from __future__ import annotations

import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for live updates."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)
        log.info(f"WebSocket connected ({len(self.active)} active)")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.remove(websocket)
        log.info(f"WebSocket disconnected ({len(self.active)} active)")

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Broadcast an event to all connected clients."""
        message = json.dumps({"type": event_type, "data": data})
        disconnected = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.active.remove(ws)


# Global instance
manager = ConnectionManager()
