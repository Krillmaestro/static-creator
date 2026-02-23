"""Progress tracker: edits a Telegram message with live pipeline status."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from telegram import Bot
from telegram.error import TelegramError

from bot.pipeline.events import Event, EventType
from bot.pipeline.models import PipelineStage

logger = logging.getLogger(__name__)

STAGE_EMOJI = {
    PipelineStage.QUEUED: "⏳",
    PipelineStage.RESEARCH: "🔍",
    PipelineStage.PROMPT_CRAFTING: "✏️",
    PipelineStage.GENERATING: "🎨",
    PipelineStage.EVALUATING: "⭐",
    PipelineStage.COMPLETE: "✅",
    PipelineStage.FAILED: "❌",
}

STAGE_LABEL = {
    PipelineStage.QUEUED: "Köar...",
    PipelineStage.RESEARCH: "Analyserar referensbilder",
    PipelineStage.PROMPT_CRAFTING: "Skapar bildprompts",
    PipelineStage.GENERATING: "Genererar bilder",
    PipelineStage.EVALUATING: "Utvärderar resultat",
    PipelineStage.COMPLETE: "Klart!",
    PipelineStage.FAILED: "Misslyckades",
}

ORDERED_STAGES = [
    PipelineStage.RESEARCH,
    PipelineStage.PROMPT_CRAFTING,
    PipelineStage.GENERATING,
    PipelineStage.EVALUATING,
]


@dataclass
class ProgressTracker:
    """Tracks one job's progress and edits a single Telegram message."""

    bot: Bot
    chat_id: int
    message_id: int
    job_id: str
    current_stage: PipelineStage = PipelineStage.QUEUED
    gen_progress: str = ""
    agent_messages: list[str] = field(default_factory=list)
    _last_text: str = ""

    def _build_text(self) -> str:
        lines = [f"🐾 *Banana Squad arbetar...*\n"]

        for stage in ORDERED_STAGES:
            emoji = STAGE_EMOJI[stage]
            label = STAGE_LABEL[stage]

            if stage == self.current_stage:
                marker = "▶️"
            elif ORDERED_STAGES.index(stage) < ORDERED_STAGES.index(self.current_stage) if self.current_stage in ORDERED_STAGES else False:
                marker = "✅"
            else:
                marker = "⬜"

            line = f"{marker} {emoji} {label}"

            if stage == PipelineStage.GENERATING and self.gen_progress:
                line += f" ({self.gen_progress})"

            lines.append(line)

        if self.agent_messages:
            lines.append("")
            lines.append(f"💬 _{self.agent_messages[-1]}_")

        return "\n".join(lines)

    async def handle_event(self, event: Event) -> None:
        """EventBus subscriber — updates Telegram message on relevant events."""
        if event.job_id != self.job_id:
            return

        if event.type == EventType.STAGE_CHANGED:
            stage_str = event.data.get("stage", "")
            try:
                self.current_stage = PipelineStage(stage_str)
            except ValueError:
                pass

        elif event.type == EventType.PROGRESS:
            current = event.data.get("current", 0)
            total = event.data.get("total", 5)
            self.gen_progress = f"{current}/{total}"

        elif event.type == EventType.AGENT_MESSAGE:
            msg = event.data.get("message", "")
            if msg:
                self.agent_messages.append(msg)
                if len(self.agent_messages) > 5:
                    self.agent_messages = self.agent_messages[-5:]

        elif event.type in (EventType.JOB_COMPLETED, EventType.JOB_FAILED):
            if event.type == EventType.JOB_COMPLETED:
                self.current_stage = PipelineStage.COMPLETE
            else:
                self.current_stage = PipelineStage.FAILED

        new_text = self._build_text()
        if new_text == self._last_text:
            return

        self._last_text = new_text
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=new_text,
                parse_mode="Markdown",
            )
        except TelegramError as e:
            if "message is not modified" not in str(e).lower():
                logger.warning("Failed to edit progress message: %s", e)
