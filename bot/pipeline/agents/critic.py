"""Critic Agent: Claude Vision evaluates and ranks 5 generated variants."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import anthropic

from bot.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from bot.pipeline.events import Event, EventType, event_bus
from bot.pipeline.models import (
    CriticResult,
    CriticScore,
    GeneratedImage,
    VariantEvaluation,
    VariantType,
)
from bot.pipeline.utils import detect_media_type

logger = logging.getLogger(__name__)

CRITIC_SYSTEM = """\
You are a professional image critic evaluating product photography variants
for ApotekHunden, a premium Swedish pet supplement brand.

Score each image on 4 dimensions (0-10 scale):
1. **Faithfulness**: Does it match the user's original request?
2. **Conciseness**: Does it focus on core information without visual clutter?
3. **Readability**: Is the layout clear, text legible, composition clean?
4. **Aesthetics**: Does it look professional and visually appealing?

Be constructive but honest. Rank all variants from best to worst."""

CRITIC_PROMPT = """\
Evaluate these {count} generated image variants for this request:

**User's original request:** {user_prompt}

The variants are labeled: {labels}

For each variant, provide scores and a brief review. Then rank them.

## Output Format
Return a JSON object:
```json
{{
  "evaluations": [
    {{
      "variant_type": "v1-faithful",
      "scores": {{
        "faithfulness": 8.5,
        "conciseness": 7.0,
        "readability": 9.0,
        "aesthetics": 8.0
      }},
      "review": "Brief constructive review..."
    }}
  ],
  "summary": "Overall assessment and recommendation...",
  "winner": "v1-faithful"
}}
```

Return ONLY the JSON, no other text.
"""


async def run_critic(
    job_id: str,
    user_prompt: str,
    images: list[GeneratedImage],
) -> CriticResult:
    """Evaluate generated images using Claude Vision."""

    successful = [img for img in images if img.success and img.file_path]

    if not successful:
        logger.warning("No successful images to evaluate")
        return CriticResult(summary="No images were generated successfully.")

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    content: list[dict] = []
    labels = []

    for img in successful:
        path = Path(img.file_path)
        if not path.exists():
            continue

        labels.append(img.variant_type.value)

        raw_bytes = path.read_bytes()
        content.append({
            "type": "text",
            "text": f"--- {img.variant_type.value} ---",
        })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": detect_media_type(raw_bytes, path.suffix),
                "data": base64.standard_b64encode(raw_bytes).decode(),
            },
        })

    content.append({
        "type": "text",
        "text": CRITIC_PROMPT.format(
            count=len(labels),
            user_prompt=user_prompt,
            labels=", ".join(labels),
        ),
    })

    await event_bus.emit(Event(
        type=EventType.AGENT_MESSAGE,
        job_id=job_id,
        data={"agent": "critic", "message": f"Evaluating {len(labels)} variants..."},
    ))

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=CRITIC_SYSTEM,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text
    logger.info("Critic agent completed (%d chars)", len(raw))

    result = _parse_critic(raw)

    # Emit individual scores
    for ev in result.evaluations:
        await event_bus.emit(Event(
            type=EventType.VARIANT_SCORED,
            job_id=job_id,
            data={
                "variant": ev.variant_type.value,
                "scores": {
                    "faithfulness": ev.scores.faithfulness,
                    "conciseness": ev.scores.conciseness,
                    "readability": ev.scores.readability,
                    "aesthetics": ev.scores.aesthetics,
                    "total": ev.scores.total,
                },
                "rank": ev.rank,
                "review": ev.review,
            },
        ))

    return result


def _parse_critic(raw: str) -> CriticResult:
    """Parse JSON from critic response."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse critic JSON: %s", text[:200])
        return CriticResult(summary="Failed to parse evaluation results.")

    evaluations = []
    for item in data.get("evaluations", []):
        scores_data = item.get("scores", {})
        try:
            vtype = VariantType(item.get("variant_type", ""))
        except ValueError:
            continue

        evaluations.append(VariantEvaluation(
            variant_type=vtype,
            scores=CriticScore(
                faithfulness=float(scores_data.get("faithfulness", 5)),
                conciseness=float(scores_data.get("conciseness", 5)),
                readability=float(scores_data.get("readability", 5)),
                aesthetics=float(scores_data.get("aesthetics", 5)),
            ),
            review=item.get("review", ""),
        ))

    # Sort by total score descending and assign ranks
    evaluations.sort(key=lambda e: e.scores.total, reverse=True)
    for rank, ev in enumerate(evaluations, 1):
        ev.rank = rank

    winner = None
    if evaluations:
        winner = evaluations[0].variant_type

    winner_str = data.get("winner", "")
    if winner_str:
        try:
            winner = VariantType(winner_str)
        except ValueError:
            pass

    return CriticResult(
        evaluations=evaluations,
        summary=data.get("summary", ""),
        winner=winner,
    )
