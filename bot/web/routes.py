"""REST API routes for the web dashboard."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from bot.pipeline.models import PipelineStage
from bot.storage.jobs import job_store

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "banana-squad"}


@router.get("/jobs")
async def list_jobs() -> JSONResponse:
    jobs = job_store.list_all()
    return JSONResponse([
        {
            "job_id": j.job_id,
            "prompt": j.request.user_prompt[:100],
            "stage": j.stage.value,
            "created_at": j.request.created_at.isoformat(),
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "image_count": sum(1 for img in j.images if img.success),
            "winner": j.evaluation.winner.value if j.evaluation and j.evaluation.winner else None,
        }
        for j in jobs
    ])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = job_store.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    images = [
        {
            "variant": img.variant_type.value,
            "file_path": img.file_path.split("/outputs/")[-1] if img.file_path else None,
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
