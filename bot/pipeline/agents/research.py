"""Research Agent: Claude Vision analysis of reference images."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import anthropic

from bot.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from bot.pipeline.models import ResearchResult
from bot.pipeline.utils import detect_media_type

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM = """\
You are a visual research analyst for a product photography team.
Analyze reference images and extract actionable insights for image generation.
Be specific about colors (hex codes when possible), composition techniques,
lighting setups, textures, and mood. Output structured analysis."""

RESEARCH_PROMPT = """\
Analyze the provided reference image(s) in detail for our image generation pipeline.

User's request context: {user_prompt}

Provide your analysis in this exact structure:

**Style Analysis:** Describe the overall visual style, photographic approach, and production quality.

**Color Palette:** List the dominant colors with approximate hex codes.

**Composition Notes:** Describe framing, perspective, rule-of-thirds usage, negative space, focal points.

**Mood:** Describe the emotional tone and atmosphere.

**Key Elements:** List the most important visual elements that should be preserved or referenced.
"""


async def run_research(
    user_prompt: str,
    reference_image_paths: list[str],
) -> ResearchResult:
    """Analyze reference images using Claude Vision."""

    if not reference_image_paths:
        logger.info("No reference images — skipping research agent")
        return ResearchResult(
            raw_analysis="No reference images provided. Proceeding with prompt-only generation.",
        )

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    content: list[dict] = []
    for img_path in reference_image_paths:
        path = Path(img_path)
        if not path.exists():
            logger.warning("Reference image not found: %s", img_path)
            continue

        raw_bytes = path.read_bytes()
        media_type = detect_media_type(raw_bytes, path.suffix)
        data = base64.standard_b64encode(raw_bytes).decode()

        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        })

    content.append({
        "type": "text",
        "text": RESEARCH_PROMPT.format(user_prompt=user_prompt),
    })

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=RESEARCH_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text
    logger.info("Research agent completed analysis (%d chars)", len(raw))

    return _parse_research(raw)


def _parse_research(raw: str) -> ResearchResult:
    """Best-effort parse of structured analysis."""
    sections = {
        "style_analysis": "",
        "color_palette": [],
        "composition_notes": "",
        "mood": "",
        "key_elements": [],
    }

    current_key = None
    lines = raw.split("\n")

    for line in lines:
        lower = line.lower().strip()
        if "style analysis" in lower:
            current_key = "style_analysis"
            parts = line.split(":", 1)
            if len(parts) > 1 and parts[1].strip():
                sections["style_analysis"] = parts[1].strip()
            continue
        elif "color palette" in lower:
            current_key = "color_palette"
            continue
        elif "composition" in lower:
            current_key = "composition_notes"
            parts = line.split(":", 1)
            if len(parts) > 1 and parts[1].strip():
                sections["composition_notes"] = parts[1].strip()
            continue
        elif "mood" in lower and "**" in line:
            current_key = "mood"
            parts = line.split(":", 1)
            if len(parts) > 1 and parts[1].strip():
                sections["mood"] = parts[1].strip()
            continue
        elif "key elements" in lower:
            current_key = "key_elements"
            continue

        stripped = line.strip().lstrip("- •*").strip()
        if not stripped:
            continue

        if current_key == "color_palette":
            sections["color_palette"].append(stripped)
        elif current_key == "key_elements":
            sections["key_elements"].append(stripped)
        elif current_key == "style_analysis":
            sections["style_analysis"] += " " + stripped
        elif current_key == "composition_notes":
            sections["composition_notes"] += " " + stripped
        elif current_key == "mood":
            sections["mood"] += " " + stripped

    return ResearchResult(
        style_analysis=sections["style_analysis"].strip(),
        color_palette=sections["color_palette"],
        composition_notes=sections["composition_notes"].strip(),
        mood=sections["mood"].strip(),
        key_elements=sections["key_elements"],
        raw_analysis=raw,
    )
