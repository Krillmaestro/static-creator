"""REST API routes for the web dashboard."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from bot.config import DEFAULT_PRODUCT_IMAGE, REFERENCE_DIR
from bot.pipeline.events import Event, EventType, event_bus
from bot.pipeline.models import PipelineRequest
from bot.pipeline.orchestrator import run_pipeline
from bot.storage.jobs import job_store
from bot.pipeline.agents.generator import run_refine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "banana-squad"}


@router.get("/jobs")
async def list_jobs(
    search: Optional[str] = None,
    sort: str = "newest",
) -> JSONResponse:
    if search:
        jobs = job_store.search(search)
    else:
        jobs = job_store.list_all()

    if sort == "oldest":
        jobs = list(reversed(jobs))

    return JSONResponse([
        {
            "job_id": j.job_id,
            "prompt": j.request.user_prompt[:120],
            "stage": j.stage.value,
            "created_at": j.request.created_at.isoformat(),
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "image_count": sum(1 for img in j.images if img.success),
            "winner": j.evaluation.winner.value if j.evaluation and j.evaluation.winner else None,
            "winner_path": _winner_path(j),
        }
        for j in jobs
    ])


def _winner_path(j) -> Optional[str]:
    """Return the output-relative path of the winning image, if any."""
    if not j.evaluation or not j.evaluation.winner:
        return None
    for img in j.images:
        if img.variant_type == j.evaluation.winner and img.success and img.file_path:
            path = img.file_path
            return path.split("/outputs/")[-1] if "/outputs/" in path else path
    return None


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = job_store.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    images = [
        {
            "variant": img.variant_type.value,
            "file_path": img.file_path.split("/outputs/")[-1] if img.file_path and "/outputs/" in img.file_path else img.file_path,
            "success": img.success,
            "error": img.error,
        }
        for img in job.images
    ]

    evaluations = []
    if job.evaluation:
        evaluations = [
            {
                "variant": ev.variant_type.value,
                "scores": {
                    "faithfulness": ev.scores.faithfulness,
                    "conciseness": ev.scores.conciseness,
                    "readability": ev.scores.readability,
                    "aesthetics": ev.scores.aesthetics,
                    "total": ev.scores.total,
                },
                "review": ev.review,
                "rank": ev.rank,
            }
            for ev in job.evaluation.evaluations
        ]

    # Build feedback map: variant → {rating, selected}
    feedback_rows = job_store.get_feedback(job_id)
    feedback = {
        fb["variant"]: {"rating": fb["rating"], "selected": fb["selected"]}
        for fb in feedback_rows
    }

    return JSONResponse({
        "job_id": job.job_id,
        "prompt": job.request.user_prompt,
        "stage": job.stage.value,
        "created_at": job.request.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "aspect_ratio": job.request.aspect_ratio,
        "resolution": job.request.resolution,
        "research": {
            "style": job.research.style_analysis,
            "colors": job.research.color_palette,
            "composition": job.research.composition_notes,
            "mood": job.research.mood,
        } if job.research else None,
        "prompts": [
            {
                "variant": p.variant_type.value,
                "label": p.label,
                "prompt": p.narrative_prompt,
            }
            for p in job.prompts
        ],
        "images": images,
        "evaluations": evaluations,
        "refinements": [
            {
                "variant": r.variant,
                "instruction": r.instruction,
                "original_path": r.original_path.split("/outputs/")[-1] if "/outputs/" in r.original_path else r.original_path,
                "refined_path": r.refined_path.split("/outputs/")[-1] if "/outputs/" in r.refined_path else r.refined_path,
                "created_at": r.created_at.isoformat(),
            }
            for r in job.refinements
        ],
        "summary": job.evaluation.summary if job.evaluation else None,
        "winner": job.evaluation.winner.value if job.evaluation and job.evaluation.winner else None,
        "error": job.error,
        "feedback": feedback,
    })


@router.post("/jobs/{job_id}/feedback")
async def submit_feedback(
    job_id: str,
    variant: str = Form(...),
    rating: int = Form(0),
    selected: bool = Form(False),
) -> JSONResponse:
    """Save feedback (thumbs up/down, selection) for a variant."""
    job = job_store.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    if rating not in (-1, 0, 1):
        return JSONResponse({"error": "Rating must be -1, 0, or 1"}, status_code=400)

    # Validate variant exists in this job
    valid_variants = {img.variant_type.value for img in job.images}
    if variant not in valid_variants:
        return JSONResponse({"error": "Invalid variant for this job"}, status_code=400)

    job_store.save_feedback(job_id, variant, rating, selected)
    return JSONResponse({"status": "ok"})


@router.post("/generate")
async def generate(
    prompt: str = Form(...),
    aspect_ratio: str = Form("1:1"),
    resolution: str = Form("2K"),
    files: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    """Accept a generation request from the web form."""

    ref_paths: list[str] = []

    # Always include the default product image first
    if DEFAULT_PRODUCT_IMAGE and DEFAULT_PRODUCT_IMAGE.exists():
        ref_paths.append(str(DEFAULT_PRODUCT_IMAGE))

    for upload in files:
        if not upload.filename:
            continue
        dest = REFERENCE_DIR / f"web-{upload.filename}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        ref_paths.append(str(dest))

    request = PipelineRequest(
        user_prompt=prompt,
        reference_image_paths=ref_paths,
        aspect_ratio=aspect_ratio,
        resolution=resolution.upper(),
    )

    # Fire pipeline in background — client tracks via WebSocket
    asyncio.create_task(run_pipeline(request))

    return JSONResponse({"job_id": request.job_id}, status_code=202)


@router.post("/refine")
async def refine(
    job_id: str = Form(...),
    variant: str = Form(...),
    instruction: str = Form(""),
) -> JSONResponse:
    """Refine a single variant image. Old image is preserved."""

    job = job_store.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    # Find the original image for this variant
    original_img = None
    for img in job.images:
        if img.variant_type.value == variant and img.success and img.file_path:
            original_img = img
            break

    if not original_img:
        return JSONResponse({"error": "Variant image not found"}, status_code=404)

    # Find the original prompt for this variant
    original_prompt = job.request.user_prompt
    for p in job.prompts:
        if p.variant_type.value == variant:
            original_prompt = p.narrative_prompt
            break

    # Run refinement in background
    async def _do_refine():
        try:
            await event_bus.emit(Event(
                type=EventType.PROGRESS,
                job_id=job_id,
                data={"agent": "generator", "message": f"Refining {variant}..."},
            ))

            refinement = await run_refine(
                job_id=job_id,
                variant=variant,
                original_image_path=original_img.file_path,
                original_prompt=original_prompt,
                instruction=instruction,
                aspect_ratio=job.request.aspect_ratio,
                resolution=job.request.resolution,
                reference_image_paths=job.request.reference_image_paths,
            )

            # Persist refinement to job
            job_fresh = job_store.get(job_id)
            if job_fresh:
                job_fresh.refinements.append(refinement)
                job_store.update_result(job_fresh)

            refined_rel = refinement.refined_path
            if "/outputs/" in refined_rel:
                refined_rel = refined_rel.split("/outputs/")[-1]

            await event_bus.emit(Event(
                type=EventType.IMAGE_REFINED,
                job_id=job_id,
                data={
                    "variant": variant,
                    "instruction": instruction,
                    "refined_path": refined_rel,
                    "original_path": original_img.file_path.split("/outputs/")[-1] if "/outputs/" in original_img.file_path else original_img.file_path,
                },
            ))

        except Exception as e:
            logger.exception("Refinement failed for %s/%s", job_id, variant)
            await event_bus.emit(Event(
                type=EventType.JOB_FAILED,
                job_id=job_id,
                data={"error": f"Refinement failed: {e}"},
            ))

    asyncio.create_task(_do_refine())

    return JSONResponse({"status": "refining", "job_id": job_id, "variant": variant}, status_code=202)
