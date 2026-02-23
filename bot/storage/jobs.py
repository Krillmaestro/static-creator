"""In-memory job store."""

from __future__ import annotations

from typing import Optional

from bot.pipeline.models import PipelineResult, PipelineStage


class JobStore:
    """Thread-safe (GIL) dict of job_id → PipelineResult."""

    def __init__(self) -> None:
        self._jobs: dict[str, PipelineResult] = {}

    def create(self, result: PipelineResult) -> None:
        self._jobs[result.job_id] = result

    def get(self, job_id: str) -> Optional[PipelineResult]:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> Optional[PipelineResult]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        for key, value in kwargs.items():
            setattr(job, key, value)
        return job

    def list_all(self) -> list[PipelineResult]:
        return sorted(
            self._jobs.values(),
            key=lambda j: j.request.created_at,
            reverse=True,
        )

    def list_active(self) -> list[PipelineResult]:
        return [
            j for j in self._jobs.values()
            if j.stage not in (PipelineStage.COMPLETE, PipelineStage.FAILED)
        ]


# Singleton
job_store = JobStore()
