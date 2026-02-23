"""Shared utilities for the pipeline."""

from __future__ import annotations


def detect_media_type(data: bytes, suffix_hint: str = "") -> str:
    """Detect image MIME type from file bytes (magic number), with suffix fallback."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"

    # Fallback to suffix
    ext = suffix_hint.lower().lstrip(".")
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")  # Default to JPEG (most common)
