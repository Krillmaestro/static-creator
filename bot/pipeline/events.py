"""EventBus: async broadcast to WebSocket clients and Telegram progress."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    # Pipeline lifecycle
    JOB_STARTED = "job_started"
    STAGE_CHANGED = "stage_changed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"

    # Agent-level
    AGENT_MESSAGE = "agent_message"
    IMAGE_GENERATED = "image_generated"
    VARIANT_SCORED = "variant_scored"

    # Progress
    PROGRESS = "progress"


@dataclass
class Event:
    type: EventType
    job_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "job_id": self.job_id,
            "data": self.data,
            "timestamp": self.timestamp,
        })


# Subscriber = async callable that receives an Event
Subscriber = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Simple pub/sub bus. Subscribers receive all events."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, callback: Subscriber) -> None:
        async with self._lock:
            self._subscribers.append(callback)

    async def unsubscribe(self, callback: Subscriber) -> None:
        async with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not callback]

    async def emit(self, event: Event) -> None:
        async with self._lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                await sub(event)
            except Exception:
                logger.exception("EventBus subscriber error")


# Singleton
event_bus = EventBus()
