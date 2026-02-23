"""Pydantic data models for the entire pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────

class PipelineStage(str, Enum):
    QUEUED = "queued"
    RESEARCH = "research"
    PROMPT_CRAFTING = "prompt_crafting"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    FAILED = "failed"


class VariantType(str, Enum):
    FAITHFUL = "v1-faithful"
    ENHANCED = "v2-enhanced"
    ALT_COMPOSITION = "v3-alt-composition"
    STYLE_VARIATION = "v4-style-variation"
    BOLD_CREATIVE = "v5-bold-creative"
    REFERENCE_COPY = "v6-reference-copy"


# ── Pipeline Request ───────────────────────────────────────────────

class PipelineRequest(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_prompt: str
    reference_image_paths: list[str] = Field(default_factory=list)
    aspect_ratio: str = "4:3"
    resolution: str = "2K"
    telegram_chat_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Research Result ────────────────────────────────────────────────

class ResearchResult(BaseModel):
    style_analysis: str = ""
    color_palette: list[str] = Field(default_factory=list)
    composition_notes: str = ""
    mood: str = ""
    key_elements: list[str] = Field(default_factory=list)
    raw_analysis: str = ""


# ── Prompt Variant ─────────────────────────────────────────────────

class PromptVariant(BaseModel):
    variant_type: VariantType
    label: str
    narrative_prompt: str
    rationale: str = ""


# ── Generated Image ────────────────────────────────────────────────

class GeneratedImage(BaseModel):
    variant_type: VariantType
    file_path: str
    gemini_text: str = ""
    success: bool = True
    error: Optional[str] = None


# ── Critic Score ───────────────────────────────────────────────────

class CriticScore(BaseModel):
    faithfulness: float = Field(ge=0, le=10)
    conciseness: float = Field(ge=0, le=10)
    readability: float = Field(ge=0, le=10)
    aesthetics: float = Field(ge=0, le=10)

    @property
    def total(self) -> float:
        return self.faithfulness + self.conciseness + self.readability + self.aesthetics


class VariantEvaluation(BaseModel):
    variant_type: VariantType
    scores: CriticScore
    review: str = ""
    rank: int = 0


class CriticResult(BaseModel):
    evaluations: list[VariantEvaluation] = Field(default_factory=list)
    summary: str = ""
    winner: Optional[VariantType] = None


# ── Pipeline Result ────────────────────────────────────────────────

class PipelineResult(BaseModel):
    job_id: str
    request: PipelineRequest
    research: Optional[ResearchResult] = None
    prompts: list[PromptVariant] = Field(default_factory=list)
    images: list[GeneratedImage] = Field(default_factory=list)
    evaluation: Optional[CriticResult] = None
    stage: PipelineStage = PipelineStage.QUEUED
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
