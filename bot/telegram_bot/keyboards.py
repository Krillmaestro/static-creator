"""Inline keyboard builders for Telegram bot."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def settings_keyboard(
    current_ratio: str = "4:3",
    current_res: str = "2K",
) -> InlineKeyboardMarkup:
    """Settings menu with aspect ratio and resolution options."""
    ratios = ["1:1", "4:3", "3:2", "16:9", "9:16", "4:5"]
    resolutions = ["1K", "2K", "4K"]

    ratio_buttons = [
        InlineKeyboardButton(
            f"{'✓ ' if r == current_ratio else ''}{r}",
            callback_data=f"ratio:{r}",
        )
        for r in ratios
    ]

    res_buttons = [
        InlineKeyboardButton(
            f"{'✓ ' if r == current_res else ''}{r}",
            callback_data=f"res:{r}",
        )
        for r in resolutions
    ]

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("── Aspect Ratio ──", callback_data="noop")],
        ratio_buttons[:3],
        ratio_buttons[3:],
        [InlineKeyboardButton("── Resolution ──", callback_data="noop")],
        res_buttons,
        [InlineKeyboardButton("Done ✓", callback_data="settings:done")],
    ])


def refinement_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Buttons to refine individual variants after generation."""
    buttons = [
        [
            InlineKeyboardButton(f"Refine v{i}", callback_data=f"refine:{job_id}:v{i}")
            for i in range(1, 4)
        ],
        [
            InlineKeyboardButton(f"Refine v{i}", callback_data=f"refine:{job_id}:v{i}")
            for i in range(4, 6)
        ],
        [InlineKeyboardButton("New Generation", callback_data=f"new:{job_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Cancel button shown during generation."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Cancel", callback_data=f"cancel:{job_id}")],
    ])
