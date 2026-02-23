"""Generator Agent: Gemini 3 Pro Image API — generates images from prompts."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from bot.config import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_RETRIES,
    OUTPUTS_DIR,
)
from bot.pipeline.events import Event, EventType, event_bus
from bot.pipeline.models import GeneratedImage, PromptVariant

logger = logging.getLogger(__name__)


def _make_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def _generate_single(
    client: genai.Client,
    prompt: str,
    aspect_ratio: str,
    resolution: str,
    reference_images: list[Image.Image] | None = None,
) -> tuple[Image.Image | None, str]:
    """Synchronous Gemini call — will be wrapped in asyncio.to_thread."""

    contents: list = []
    if reference_images:
        for ref_img in reference_images:
            contents.append(ref_img)
        # Tell Gemini what the reference images are
        contents.append(
            "The first attached image is the REAL ApotekHunden product jar. "
            "IF a product jar or packaging appears in the generated image, it MUST "
            "be this exact jar — same shape, white container, forest green label, "
            "logo, and text. Do NOT invent a different jar design. "
            "ALL text in the image MUST be in Swedish — no English.\n\n"
        )
    contents.append(prompt)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=resolution,
            ),
        ),
    )

    result_image = None
    result_text = ""

    if response.parts:
        for part in response.parts:
            if hasattr(part, "thought") and part.thought:
                continue
            if part.text is not None:
                result_text += part.text
            elif part.inline_data is not None:
                result_image = part.as_image()

    return result_image, result_text


async def run_generator(
    job_id: str,
    prompts: list[PromptVariant],
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str = DEFAULT_RESOLUTION,
    reference_image_paths: list[str] | None = None,
) -> list[GeneratedImage]:
    """Generate images sequentially with progress events."""

    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    client = _make_client()

    # Load reference images once
    ref_images: list[Image.Image] | None = None
    if reference_image_paths:
        ref_images = []
        for p in reference_image_paths:
            path = Path(p)
            if path.exists():
                ref_images.append(Image.open(path))

    results: list[GeneratedImage] = []

    for i, variant in enumerate(prompts):
        await event_bus.emit(Event(
            type=EventType.PROGRESS,
            job_id=job_id,
            data={
                "agent": "generator",
                "message": f"Generating image {i + 1}/{len(prompts)}: {variant.label}",
                "current": i + 1,
                "total": len(prompts),
            },
        ))

        success = False
        last_error = ""

        for attempt in range(MAX_RETRIES + 1):
            try:
                image, text = await asyncio.to_thread(
                    _generate_single,
                    client,
                    variant.narrative_prompt,
                    aspect_ratio,
                    resolution,
                    ref_images,
                )

                if image is None:
                    last_error = "No image in Gemini response (safety filter?)"
                    logger.warning(
                        "Attempt %d/%d for %s: %s",
                        attempt + 1, MAX_RETRIES + 1, variant.variant_type.value, last_error,
                    )
                    continue

                file_name = f"{variant.variant_type.value}.png"
                file_path = job_dir / file_name
                image.save(str(file_path))

                results.append(GeneratedImage(
                    variant_type=variant.variant_type,
                    file_path=str(file_path),
                    gemini_text=text,
                    success=True,
                ))

                await event_bus.emit(Event(
                    type=EventType.IMAGE_GENERATED,
                    job_id=job_id,
                    data={
                        "variant": variant.variant_type.value,
                        "file_path": str(file_path),
                        "index": i + 1,
                    },
                ))

                success = True
                break

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Attempt %d/%d for %s failed: %s",
                    attempt + 1, MAX_RETRIES + 1, variant.variant_type.value, last_error,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 * (attempt + 1))

        if not success:
            results.append(GeneratedImage(
                variant_type=variant.variant_type,
                file_path="",
                success=False,
                error=last_error,
            ))

    logger.info(
        "Generator completed: %d/%d successful",
        sum(1 for r in results if r.success), len(results),
    )
    return results
