"""WebSocket connection manager for real-time dashboard updates."""

from __future__ import annotations

import logging

from fastapi import WebSocket

from bot.pipeline.events import Event, event_bus

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]
        logger.info("WebSocket disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def handle_event(self, event: Event) -> None:
        """EventBus subscriber — forwards all events to WebSocket clients."""
        await self.broadcast(event.to_json())


# Singleton
ws_manager = ConnectionManager()


async def setup_ws_events() -> None:
    """Subscribe the WebSocket manager to the EventBus."""
    await event_bus.subscribe(ws_manager.handle_event)
