"""Telegram bot application builder and handler registration."""

from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import TELEGRAM_BOT_TOKEN
from bot.telegram_bot.handlers import (
    callback_handler,
    cancel_handler,
    help_handler,
    photo_handler,
    settings_handler,
    start_handler,
    status_handler,
    text_handler,
)

logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Build and configure the Telegram bot application."""

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("cancel", cancel_handler))

    # Photo handler (before text so photos with captions are caught)
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    # Text handler (any non-command text triggers generation)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        text_handler,
    ))

    # Callback query handler (inline keyboard buttons)
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Telegram bot application configured")
    return app
