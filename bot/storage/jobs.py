"""Job store — SQLite-backed, persistent across restarts."""

from __future__ import annotations

from bot.config import DATA_DIR
from bot.storage.database import SqliteJobStore

# Singleton — drop-in replacement for the old in-memory JobStore
job_store = SqliteJobStore(DATA_DIR / "banana_squad.db")
