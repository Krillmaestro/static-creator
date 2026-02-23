"""Pipeline orchestrator: wires agents together in sequence with events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot.pipeline.agents.critic import run_critic
from bot.pipeline.agents.generator import run_generator
from bot.pipeline.agents.prompt_architect import run_prompt_architect
from bot.pipeline.agents.research import run_research
from bot.pipeline.events import Event, EventType, event_bus
from bot.pipeline.models import PipelineRequest, PipelineResult, PipelineStage
from bot.storage.jobs import job_store

logger = logging.getLogger(__name__)


async def run_pipeline(request: PipelineRequest) -> PipelineResult:
    """Execute the full 4-agent pipeline for a single request."""

    result = PipelineResult(
        job_id=request.job_id,
        request=request,
        stage=PipelineStage.QUEUED,
        started_at=datetime.now(timezone.utc),
    )
    job_store.create(result)

    await event_bus.emit(Event(
        type=EventType.JOB_STARTED,
        job_id=request.job_id,
        data={"prompt": request.user_prompt},
    ))

    try:
        # ── Stage 1: Research ──────────────────────────────────────
        result.stage = PipelineStage.RESEARCH
        await event_bus.emit(Event(
            type=EventType.STAGE_CHANGED,
            job_id=request.job_id,
            data={"stage": PipelineStage.RESEARCH.value},
        ))
        await event_bus.emit(Event(
            type=EventType.AGENT_MESSAGE,
            job_id=request.job_id,
            data={"agent": "research", "message": "Analyzing reference images..."},
        ))

        research = await run_research(
            user_prompt=request.user_prompt,
            reference_image_paths=request.reference_image_paths,
        )
        result.research = research

        await event_bus.emit(Event(
            type=EventType.AGENT_MESSAGE,
            job_id=request.job_id,
            data={
                "agent": "research",
                "message": f"Analysis complete. Style: {research.style_analysis[:100]}..."
                if research.style_analysis else "No reference images — using prompt-only mode.",
            },
        ))

        # ── Stage 2: Prompt Crafting ───────────────────────────────
        result.stage = PipelineStage.PROMPT_CRAFTING
        await event_bus.emit(Event(
            type=EventType.STAGE_CHANGED,
            job_id=request.job_id,
            data={"stage": PipelineStage.PROMPT_CRAFTING.value},
        ))
        await event_bus.emit(Event(
            type=EventType.AGENT_MESSAGE,
            job_id=request.job_id,
            data={"agent": "prompt_architect", "message": "Crafting 5 narrative prompts..."},
        ))

        prompts = await run_prompt_architect(
            user_prompt=request.user_prompt,
            research=research,
        )
        result.prompts = prompts

        await event_bus.emit(Event(
            type=EventType.AGENT_MESSAGE,
            job_id=request.job_id,
            data={
                "agent": "prompt_architect",
                "message": f"Created {len(prompts)} prompt variants.",
            },
        ))

        # ── Stage 3: Image Generation ─────────────────────────────
        result.stage = PipelineStage.GENERATING
        await event_bus.emit(Event(
            type=EventType.STAGE_CHANGED,
            job_id=request.job_id,
            data={"stage": PipelineStage.GENERATING.value},
        ))

        images = await run_generator(
            job_id=request.job_id,
            prompts=prompts,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            reference_image_paths=request.reference_image_paths,
        )
        result.images = images

        successful = sum(1 for img in images if img.success)
        await event_bus.emit(Event(
            type=EventType.AGENT_MESSAGE,
            job_id=request.job_id,
            data={
                "agent": "generator",
                "message": f"Generated {successful}/{len(images)} images successfully.",
            },
        ))

        # ── Stage 4: Evaluation ────────────────────────────────────
        if successful > 0:
            result.stage = PipelineStage.EVALUATING
            await event_bus.emit(Event(
                type=EventType.STAGE_CHANGED,
                job_id=request.job_id,
                data={"stage": PipelineStage.EVALUATING.value},
            ))

            evaluation = await run_critic(
                job_id=request.job_id,
                user_prompt=request.user_prompt,
                images=images,
            )
            result.evaluation = evaluation

            await event_bus.emit(Event(
                type=EventType.AGENT_MESSAGE,
                job_id=request.job_id,
                data={
                    "agent": "critic",
                    "message": f"Evaluation complete. Winner: {evaluation.winner.value if evaluation.winner else 'N/A'}",
                },
            ))

        # ── Complete ───────────────────────────────────────────────
        result.stage = PipelineStage.COMPLETE
        result.completed_at = datetime.now(timezone.utc)

        await event_bus.emit(Event(
            type=EventType.JOB_COMPLETED,
            job_id=request.job_id,
            data={
                "successful_images": successful,
                "winner": result.evaluation.winner.value if result.evaluation and result.evaluation.winner else None,
            },
        ))

        logger.info("Pipeline completed for job %s", request.job_id)
        return result

    except Exception as e:
        result.stage = PipelineStage.FAILED
        result.error = str(e)
        result.completed_at = datetime.now(timezone.utc)

        await event_bus.emit(Event(
            type=EventType.JOB_FAILED,
            job_id=request.job_id,
            data={"error": str(e)},
        ))

        logger.exception("Pipeline failed for job %s", request.job_id)
        return result
