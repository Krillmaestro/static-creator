# Banana Squad — AI Image Generation Agent Team

## Project Overview

This project uses the **PaperBanana agentic framework** to generate professional-quality images using the **Gemini 3 Pro Image API (Nano Banana Pro)**. The system orchestrates 4 specialized agents (+ 1 Lead) that collaborate through Claude Code's Agent Teams feature.

## Team Architecture

| Role | Agent | Responsibility |
|---|---|---|
| **Lead** | Coordinator | Gathers user requirements, delegates work, presents results |
| **Research Agent** | Retriever | Analyzes reference images for style, composition, color |
| **Prompt Architect** | Planner + Stylist | Crafts 5 distinct narrative image prompts |
| **Generator Agent** | Visualizer | Calls Gemini API to generate images |
| **Critic Agent** | Critic | Evaluates and ranks all 5 variants |

## Project Structure

```
.
├── CLAUDE.md                       # This file — project rules and context
├── .env                            # GEMINI_API_KEY (never commit)
├── gemini-3-image-api-guide.md     # Complete Gemini 3 Pro Image API reference
├── paperbanana.md                  # PaperBanana research paper
├── spawn-team-prompt.md            # The prompt to spawn the agent team
├── reference-images/               # User-provided reference images
├── outputs/                        # Generated images land here
└── diagrams/                       # Explanatory diagrams about the system
```

## API Quick Reference

- **Model**: `gemini-3-pro-image-preview`
- **SDK**: `google-genai` (Python) or `@google/genai` (JS)
- **API key**: Loaded from `.env` → `GEMINI_API_KEY`
- **Response modalities**: `['TEXT', 'IMAGE']`
- **Aspect ratios**: `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`
- **Resolutions**: `"1K"`, `"2K"`, `"4K"` — **MUST be uppercase K**
- **Max reference images**: 14 (6 objects + 5 humans with high fidelity)
- **Thinking mode**: Always on, cannot be disabled

## Critical Rules

1. **Always load API key from `.env`** — never hardcode it
2. **Resolution values MUST use uppercase K** — `"2K"` not `"2k"`
3. **Prompts must be narrative paragraphs** — never keyword lists
4. **Save all outputs to `outputs/`** with descriptive filenames
5. **Always generate 5 variants** per request:
   - v1: Faithful (closest to user's request)
   - v2: Enhanced (elevated production quality)
   - v3: Alternative Composition (different angle/layout)
   - v4: Style Variation (different artistic treatment)
   - v5: Bold/Creative (experimental push)
6. **The Lead coordinates only** — never generates images itself
7. **Research Agent** only analyzes images the Lead specifies — does NOT scan broadly unless told to
8. **Generator Agent** retries up to 2 times on API failures
9. **Critic Agent** evaluates on 4 dimensions: Faithfulness, Conciseness, Readability, Aesthetics

## Python Script Template

```python
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents="Your detailed narrative prompt here",
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        image_config=types.ImageConfig(
            aspect_ratio="16:9",
            image_size="2K"
        ),
    )
)

for part in response.parts:
    if part.text is not None:
        print(part.text)
    elif part.inline_data is not None:
        image = part.as_image()
        image.save("outputs/output.png")
```

## Evaluation Dimensions (from PaperBanana)

1. **Faithfulness**: Does the image match the user's original request?
2. **Conciseness**: Does it focus on core information without visual clutter?
3. **Readability**: Is the layout clear, text legible, composition clean?
4. **Aesthetics**: Does it look professional and visually appealing?

## Reference Files

- For API details → read `gemini-3-image-api-guide.md`
- For framework theory → read `paperbanana.md`
- For spawn prompt → read `spawn-team-prompt.md`
