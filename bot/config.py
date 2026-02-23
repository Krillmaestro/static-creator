"""Configuration: environment variables, brand constants, defaults."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env ──────────────────────────────────────────────────────
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── API keys ───────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ── Access control ─────────────────────────────────────────────────
ALLOWED_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}

# ── Server ─────────────────────────────────────────────────────────
PORT: int = int(os.environ.get("PORT", "8000"))

# ── Paths ──────────────────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data")))
OUTPUTS_DIR: Path = Path(os.environ.get("OUTPUTS_DIR", str(PROJECT_ROOT / "outputs")))
REFERENCE_DIR: Path = PROJECT_ROOT / "reference-images"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_DIR.mkdir(exist_ok=True)

# ── Gemini defaults ────────────────────────────────────────────────
GEMINI_MODEL: str = "gemini-3-pro-image-preview"
DEFAULT_ASPECT_RATIO: str = "1:1"
DEFAULT_RESOLUTION: str = "2K"  # MUST be uppercase K
MAX_RETRIES: int = 2

# ── Claude defaults ────────────────────────────────────────────────
CLAUDE_MODEL: str = "claude-sonnet-4-20250514"

# ── Brand constants (ApotekHunden) ─────────────────────────────────
BRAND = {
    "name": "ApotekHunden",
    "product": "Probiotika för Hundar",
    "colors": {
        "forest": "#2C5530",
        "main_green": "#30574c",
        "cream": "#FAF7F2",
        "bark": "#3D2E1E",
        "amber": "#C8924A",
        "soft_green": "#EFF5EF",
    },
    "typography": {
        "headline": "DM Serif Display",
        "body": "DM Sans",
    },
    "tone": "Premium, natural, trustworthy, Scandinavian",
    "language": "Swedish",
}

# ── Default product image (always included as reference) ───────────
# Place your product jar image in reference-images/product-jar.png (or .jpg)
# It will be auto-included in every generation request.
_product_candidates = [
    REFERENCE_DIR / "product-jar.png",
    REFERENCE_DIR / "product-jar.jpg",
    REFERENCE_DIR / "product-jar.jpeg",
    REFERENCE_DIR / "product-jar.webp",
]
DEFAULT_PRODUCT_IMAGE: Path | None = next(
    (p for p in _product_candidates if p.exists()), None
)

# ── Pipeline ───────────────────────────────────────────────────────
VARIANT_LABELS: list[str] = [
    "v1-faithful",
    "v2-enhanced",
    "v3-alt-composition",
    "v4-style-variation",
    "v5-bold-creative",
    "v6-reference-copy",
]
NUM_VARIANTS: int = 6
