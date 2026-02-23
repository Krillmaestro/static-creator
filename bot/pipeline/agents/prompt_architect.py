"""Prompt Architect Agent: Claude crafts 6 narrative image prompts."""

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
1. Write exactly 6 prompts — one for each variant type (v1 through v6)
2. Each prompt must be 5-8 sentences of rich narrative description
3. Every prompt MUST describe a COMPLETE AD STATIC containing:
   - Bold Swedish headline text at the top of the image
   - Subheadline text beneath the headline (in Swedish)
   - 3-4 rounded benefit badges/pills with short SWEDISH text
   - A CTA banner at the bottom of the image (in Swedish)
4. Include specific visual details: typography style, badge shapes, layout grid,
   background scene, lighting, color values from the brand palette
5. ALL text in images MUST be in Swedish — specify exact Swedish text strings.
   NEVER write benefit badges or any text in English. Examples:
   - "Stärker tarmfloran" NOT "Supports gut health"
   - "Naturliga ingredienser" NOT "Natural ingredients"
   - "Veterinärrekommenderad" NOT "Vet recommended"
6. Describe the image AS A DESIGNED AD, not as a photograph alone
7. When the user provides a reference image, describe the layout and style
   elements from that reference and incorporate them

## Product Jar Rule — IMPORTANT
The product jar does NOT need to appear in every variant — in fact, MOST variants
should NOT include the jar unless the user specifically asks for it or the ad concept
requires showing the product. Only include a jar when it makes sense for the
composition. If you DO include a jar, add this instruction in that prompt:
"Use the exact ApotekHunden product jar from the attached reference photo —
reproduce its shape, white container, forest green label, logo, and text faithfully."

## v6 — Reference Copy (MANDATORY)
v6 ALWAYS recreates the user's reference image (or the ad they described) nearly
identically — same layout, same composition, same angles — but re-branded with
ApotekHunden's colors, Swedish text, and (if a jar is visible in the reference)
the real product jar. Only include a jar in v6 if the reference image shows one.
The v6 prompt MUST describe the reference image's layout in precise spatial detail
(positions, sizes, arrangements) so that Gemini can replicate it accurately.
"""

ARCHITECT_PROMPT = """\
Create 6 social media ad static prompts for the Gemini 3 Pro Image API.
These are PAID AD CREATIVES, not product photos. Each must be a complete ad
with headline, benefits, and CTA. ALL TEXT IN SWEDISH — no English anywhere.

## User's Request
{user_prompt}

## Research Findings
{research_context}

## Variant Definitions
{variant_defs}

{learning_context}

## Example of a Good Prompt (for reference only — do NOT copy)
"Create a professional social media ad static for a Swedish dog supplement brand. \
At the top of the image, display bold white headline text reading 'Ge din hund \
en friskare mage' in a premium serif font, with a smaller subheadline below \
reading 'Naturlig probiotika — Svensktillverkad'. The background shows a happy \
golden retriever on a green sunlit meadow with soft bokeh. Below the headline, \
arrange four rounded cream-colored benefit badges in a 2x2 grid, each containing \
a small icon and Swedish text: 'Stärker tarmfloran', 'Inga kemikalier', 'Lugnar \
känslig mage', 'Stödjer immunförsvaret'. At the very bottom, add a forest green \
CTA banner with white text reading 'Mindre magproblem på 4-6 veckor'. Color palette: \
forest green #2C5530, cream #FAF7F2, amber #C8924A accents."

## Output Format
Return a JSON array with exactly 6 objects:
```json
[
  {{
    "variant_type": "v1-faithful",
    "label": "Short descriptive label",
    "narrative_prompt": "The full narrative prompt paragraph for Gemini...",
    "rationale": "Why this variant approaches it this way"
  }},
  ...
  {{
    "variant_type": "v6-reference-copy",
    "label": "Reference copy — ApotekHunden branded",
    "narrative_prompt": "Near-identical recreation of the reference image...",
    "rationale": "Direct adaptation of the reference with ApotekHunden branding"
  }}
]
```

Return ONLY the JSON array, no other text.
"""


def build_learning_context(top_prompts: list[dict], limit: int = 5) -> str:
    """Format top-performing prompts as learning context for the architect."""
    if not top_prompts:
        return "Ingen historisk feedback ännu — lita på din expertis."

    examples = top_prompts[:limit]
    lines = ["## Framgångsrika exempel\n",
             "Dessa prompter har fått positiv feedback från användaren. "
             "Lär av deras stil, struktur och tillvägagångssätt:\n"]

    for i, ex in enumerate(examples, 1):
        selected_tag = " [VALD AV ANVÄNDAREN]" if ex.get("selected") else ""
        lines.append(f"### Exempel {i}{selected_tag}")
        lines.append(f"**Användarens prompt:** {ex.get('user_prompt', 'N/A')}")
        lines.append(f"**Variant:** {ex.get('variant', 'N/A')}")
        if ex.get("prompt_text"):
            lines.append(f"**Framgångsrik bildprompt:** {ex['prompt_text'][:500]}")
        lines.append("")

    return "\n".join(lines)


async def run_prompt_architect(
    user_prompt: str,
    research: ResearchResult | None,
    learning_context: str = "",
) -> list[PromptVariant]:
    """Craft 6 narrative prompts using Claude."""

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

    if not learning_context:
        learning_context = "Ingen historisk feedback ännu — lita på din expertis."

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=ARCHITECT_SYSTEM,
        messages=[{
            "role": "user",
            "content": ARCHITECT_PROMPT.format(
                user_prompt=user_prompt,
                research_context=research_context,
                variant_defs=variant_defs,
                learning_context=learning_context,
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

    if len(variants) != 6:
        logger.warning("Expected 6 variants, got %d", len(variants))

    return variants
