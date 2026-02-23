"""Prompt Architect Agent: Claude crafts 5 narrative image prompts."""

from __future__ import annotations

import json
import logging

import anthropic

from bot.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from bot.pipeline.brand_context import BRAND_SYSTEM_PROMPT, VARIANT_INSTRUCTIONS
from bot.pipeline.models import PromptVariant, ResearchResult, VariantType

logger = logging.getLogger(__name__)

ARCHITECT_SYSTEM = f"""\
{BRAND_SYSTEM_PROMPT}

## Your Role
You are a Prompt Architect specializing in crafting narrative image prompts for
the Gemini 3 Pro Image API. You create prompts for SOCIAL MEDIA AD STATICS
(paid ad creatives), NOT simple product photos.

## Critical Rules
1. Write exactly 5 prompts — one for each variant type
2. Each prompt must be 5-8 sentences of rich narrative description
3. Every prompt MUST describe a COMPLETE AD STATIC containing:
   - Bold Swedish headline text at the top of the image
   - Subheadline text beneath the headline
   - The ApotekHunden product jar/packaging prominently visible
   - 3-4 rounded benefit badges/pills with short Swedish text
   - A CTA banner at the bottom of the image
4. Include specific visual details: typography style, badge shapes, layout grid,
   background scene, lighting, color values from the brand palette
5. All text in images must be in Swedish — specify exact Swedish text strings
6. Describe the image AS A DESIGNED AD, not as a photograph alone
7. When the user provides a reference image, describe the layout and style
   elements from that reference and incorporate them

## MANDATORY — Product Jar Reference Image Rule
A reference photo of the REAL ApotekHunden product jar is ALWAYS attached to the
Gemini API call. Every single narrative prompt you write MUST begin with this
exact sentence (before any other description):

"Using the attached reference photo of the ApotekHunden product jar, reproduce
that exact jar — its shape, white container, forest green label, logo, and text
— faithfully in this image."

This is non-negotiable. The purpose is to force Gemini to copy the real product
packaging pixel-accurately instead of inventing a generic jar. After that opening
sentence, continue with the rest of your ad static description.
"""

ARCHITECT_PROMPT = """\
Create 5 social media ad static prompts for the Gemini 3 Pro Image API.
These are PAID AD CREATIVES, not product photos. Each must be a complete ad
with headline, product, benefits, and CTA.

## User's Request
{user_prompt}

## Research Findings
{research_context}

## Variant Definitions
{variant_defs}

## Example of a Good Prompt (for reference only — do NOT copy)
"Using the attached reference photo of the ApotekHunden product jar, reproduce \
that exact jar — its shape, white container, forest green label, logo, and text \
— faithfully in this image. Create a professional social media ad static for a \
dog supplement brand. At the top of the image, display bold white headline text \
reading 'Ge din hund en friskare mage' in a premium serif font, with a smaller \
subheadline below reading 'Naturlig probiotika — Svensktillverkad'. The background \
shows a happy golden retriever on a green sunlit meadow with soft bokeh. In the \
center of the image, prominently place the exact ApotekHunden product jar from the \
reference photo. Below the product, arrange four rounded cream-colored benefit badges \
in a 2x2 grid, each containing a small icon and Swedish text: 'Stärker tarmfloran', \
'Inga kemikalier', 'Lugnar känslig mage', 'Stödjer immunförsvaret'. At the very \
bottom, add a forest green CTA banner with white text reading 'Mindre magproblem \
på 4-6 veckor'. Color palette: forest green #2C5530, cream #FAF7F2, amber #C8924A accents."

## Output Format
Return a JSON array with exactly 5 objects:
```json
[
  {{
    "variant_type": "v1-faithful",
    "label": "Short descriptive label",
    "narrative_prompt": "The full narrative prompt paragraph for Gemini...",
    "rationale": "Why this variant approaches it this way"
  }},
  ...
]
```

Return ONLY the JSON array, no other text.
"""


async def run_prompt_architect(
    user_prompt: str,
    research: ResearchResult | None,
) -> list[PromptVariant]:
    """Craft 5 narrative prompts using Claude."""

    research_context = "No reference images analyzed."
    if research and research.raw_analysis:
        research_context = (
            f"Style: {research.style_analysis}\n"
            f"Colors: {', '.join(research.color_palette)}\n"
            f"Composition: {research.composition_notes}\n"
            f"Mood: {research.mood}\n"
            f"Key elements: {', '.join(research.key_elements)}"
        )

    variant_defs = "\n".join(
        f"- **{vtype}**: {desc}"
        for vtype, desc in VARIANT_INSTRUCTIONS.items()
    )

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        system=ARCHITECT_SYSTEM,
        messages=[{
            "role": "user",
            "content": ARCHITECT_PROMPT.format(
                user_prompt=user_prompt,
                research_context=research_context,
                variant_defs=variant_defs,
            ),
        }],
    )

    raw = response.content[0].text
    logger.info("Prompt architect completed (%d chars)", len(raw))

    return _parse_prompts(raw)


def _parse_prompts(raw: str) -> list[PromptVariant]:
    """Parse JSON array of prompts from Claude's response."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse prompt architect JSON: %s", text[:200])
        raise ValueError("Prompt Architect returned invalid JSON")

    variants = []
    for item in data:
        vtype = item.get("variant_type", "")
        try:
            variant_enum = VariantType(vtype)
        except ValueError:
            logger.warning("Unknown variant type: %s, skipping", vtype)
            continue

        variants.append(PromptVariant(
            variant_type=variant_enum,
            label=item.get("label", vtype),
            narrative_prompt=item.get("narrative_prompt", ""),
            rationale=item.get("rationale", ""),
        ))

    if len(variants) != 5:
        logger.warning("Expected 5 variants, got %d", len(variants))

    return variants
