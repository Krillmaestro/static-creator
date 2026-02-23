"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from bot.config import OUTPUTS_DIR
from bot.web.routes import router
from bot.web.websocket import ws_manager

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Banana Squad Dashboard", docs_url=None, redoc_url=None)

    # REST API
    app.include_router(router)

    # WebSocket endpoint
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()  # Keep connection alive
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    # Mount outputs directory for image serving
    app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

    # Mount static files (dashboard)
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
