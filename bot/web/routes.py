"""REST API routes for the web dashboard."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from bot.config import DEFAULT_PRODUCT_IMAGE, REFERENCE_DIR
from bot.pipeline.models import PipelineRequest
from bot.pipeline.orchestrator import run_pipeline
from bot.storage.jobs import job_store

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
        "summary": job.evaluation.summary if job.evaluation else None,
        "winner": job.evaluation.winner.value if job.evaluation and job.evaluation.winner else None,
        "error": job.error,
    })


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
