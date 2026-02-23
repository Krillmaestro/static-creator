"""Entry point: runs Telegram polling + FastAPI/uvicorn in one asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import uvicorn

from bot.config import PORT, TELEGRAM_BOT_TOKEN
from bot.telegram_bot.bot import build_application
from bot.web.app import create_app
from bot.web.websocket import setup_ws_events

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("banana-squad")


async def main() -> None:
    logger.info("Starting Banana Squad platform...")

    # Set up WebSocket event forwarding
    await setup_ws_events()

    # Create FastAPI app
    fastapi_app = create_app()

    # Configure uvicorn
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=False,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    if TELEGRAM_BOT_TOKEN:
        # Build Telegram bot
        telegram_app = build_application()

        # Initialize the Telegram application
        await telegram_app.initialize()
        await telegram_app.start()

        # Start polling (non-blocking)
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started polling")

        try:
            # Run uvicorn (blocks until shutdown)
            await uvicorn_server.serve()
        finally:
            # Graceful shutdown
            logger.info("Shutting down...")
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()
    else:
        logger.warning("No TELEGRAM_BOT_TOKEN — running web dashboard only")
        await uvicorn_server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        sys.exit(0)
