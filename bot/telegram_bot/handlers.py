"""Telegram handlers: /start, /help, /settings, text, photo, callbacks."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS, DEFAULT_PRODUCT_IMAGE, OUTPUTS_DIR
from bot.pipeline.events import event_bus
from bot.pipeline.models import PipelineRequest
from bot.pipeline.orchestrator import run_pipeline
from bot.telegram_bot.keyboards import (
    cancel_keyboard,
    refinement_keyboard,
    settings_keyboard,
)
from bot.telegram_bot.progress import ProgressTracker

logger = logging.getLogger(__name__)

# Per-user settings stored in memory
_user_settings: dict[int, dict] = {}
# Active jobs per user
_active_jobs: dict[int, str] = {}


def _get_settings(user_id: int) -> dict:
    if user_id not in _user_settings:
        _user_settings[user_id] = {"aspect_ratio": "4:3", "resolution": "2K"}
    return _user_settings[user_id]


def _default_refs() -> list[str]:
    """Return the default product image path if configured."""
    if DEFAULT_PRODUCT_IMAGE and DEFAULT_PRODUCT_IMAGE.exists():
        return [str(DEFAULT_PRODUCT_IMAGE)]
    return []


def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # No allowlist = open access
    return user_id in ALLOWED_USER_IDS


# ── Commands ───────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text(
            f"⛔ Du har inte åtkomst. Ditt användar-ID: `{user.id}`\n"
            "Skicka detta ID till administratören.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"🐾 *Välkommen till Banana Squad, {user.first_name}!*\n\n"
        "Skicka mig en textbeskrivning av bilden du vill skapa, "
        "så genererar jag 5 professionella varianter åt dig.\n\n"
        "📸 Du kan även skicka en referensbild med bildtext.\n\n"
        "*Kommandon:*\n"
        "/settings — Ändra bildformat & upplösning\n"
        "/help — Visa hjälp\n"
        "/status — Se aktiva jobb\n"
        "/cancel — Avbryt pågående generation",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return

    await update.message.reply_text(
        "🐾 *Banana Squad — Hjälp*\n\n"
        "*Så här fungerar det:*\n"
        "1. Skriv vad du vill ha för bild\n"
        "2. Fyra AI-agenter samarbetar:\n"
        "   🔍 Forskning → ✏️ Promptdesign → 🎨 Bildgenerering → ⭐ Utvärdering\n"
        "3. Du får 5 varianter rankade efter kvalitet\n\n"
        "*Tips:*\n"
        "• Beskriv bilden detaljerat — stämning, vinkel, ljussättning\n"
        "• Skicka referensbilder för bättre resultat\n"
        "• Använd /settings för att ändra format\n\n"
        "*Varianter:*\n"
        "v1: Trogen — närmast din beskrivning\n"
        "v2: Förbättrad — högre produktionskvalitet\n"
        "v3: Alt komposition — annan vinkel/layout\n"
        "v4: Stilvariation — annat konstnärligt uttryck\n"
        "v5: Kreativ — experimentell tolkning",
        parse_mode="Markdown",
    )


async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return

    settings = _get_settings(update.effective_user.id)
    await update.message.reply_text(
        "⚙️ *Inställningar*\n\nVälj bildformat och upplösning:",
        parse_mode="Markdown",
        reply_markup=settings_keyboard(
            settings["aspect_ratio"], settings["resolution"]
        ),
    )


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return

    user_id = update.effective_user.id
    job_id = _active_jobs.get(user_id)
    if job_id:
        await update.message.reply_text(f"🔄 Aktivt jobb: `{job_id}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Inga aktiva jobb.")


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return

    user_id = update.effective_user.id
    job_id = _active_jobs.pop(user_id, None)
    if job_id:
        await update.message.reply_text(f"❌ Jobb `{job_id}` avbrutet.", parse_mode="Markdown")
    else:
        await update.message.reply_text("Inget aktivt jobb att avbryta.")


# ── Text message → generation ──────────────────────────────────────

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any text message triggers image generation."""
    user = update.effective_user
    if not _is_allowed(user.id):
        return

    if user.id in _active_jobs:
        await update.message.reply_text(
            "⏳ Du har redan ett aktivt jobb. Vänta tills det är klart eller använd /cancel."
        )
        return

    settings = _get_settings(user.id)
    request = PipelineRequest(
        user_prompt=update.message.text,
        reference_image_paths=_default_refs(),
        aspect_ratio=settings["aspect_ratio"],
        resolution=settings["resolution"],
        telegram_chat_id=update.effective_chat.id,
        telegram_message_id=update.message.message_id,
    )

    _active_jobs[user.id] = request.job_id

    await _run_and_respond(update, context, request)


# ── Photo + caption → generation with reference ────────────────────

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo with caption triggers generation with reference image."""
    user = update.effective_user
    if not _is_allowed(user.id):
        return

    if user.id in _active_jobs:
        await update.message.reply_text(
            "⏳ Du har redan ett aktivt jobb. Vänta tills det är klart eller använd /cancel."
        )
        return

    caption = update.message.caption or "Skapa en professionell ad static baserad på denna referensbild"
    photo = update.message.photo[-1]  # Largest resolution

    file = await photo.get_file()
    ref_path = OUTPUTS_DIR / f"ref_{user.id}_{photo.file_id[-8:]}.jpg"
    await file.download_to_drive(str(ref_path))

    # Combine user-uploaded reference with default product image
    ref_paths = [str(ref_path)] + _default_refs()

    settings = _get_settings(user.id)
    request = PipelineRequest(
        user_prompt=caption,
        reference_image_paths=ref_paths,
        aspect_ratio=settings["aspect_ratio"],
        resolution=settings["resolution"],
        telegram_chat_id=update.effective_chat.id,
        telegram_message_id=update.message.message_id,
    )

    _active_jobs[user.id] = request.job_id

    await _run_and_respond(update, context, request)


# ── Callback queries (settings, refinement) ────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    if data == "noop":
        return

    if data.startswith("ratio:"):
        ratio = data.split(":", 1)[1]
        _get_settings(user_id)["aspect_ratio"] = ratio
        settings = _get_settings(user_id)
        await query.edit_message_reply_markup(
            reply_markup=settings_keyboard(settings["aspect_ratio"], settings["resolution"])
        )

    elif data.startswith("res:"):
        res = data.split(":", 1)[1]
        _get_settings(user_id)["resolution"] = res
        settings = _get_settings(user_id)
        await query.edit_message_reply_markup(
            reply_markup=settings_keyboard(settings["aspect_ratio"], settings["resolution"])
        )

    elif data == "settings:done":
        settings = _get_settings(user_id)
        await query.edit_message_text(
            f"✅ Inställningar sparade!\n"
            f"Format: {settings['aspect_ratio']}\n"
            f"Upplösning: {settings['resolution']}"
        )

    elif data.startswith("refine:"):
        parts = data.split(":")
        if len(parts) == 3:
            job_id, variant = parts[1], parts[2]
            await query.edit_message_text(
                f"✏️ Förfining av {variant} från jobb {job_id}...\n"
                "Skriv vad du vill ändra som svar på detta meddelande."
            )

    elif data.startswith("cancel:"):
        job_id = data.split(":", 1)[1]
        _active_jobs.pop(user_id, None)
        await query.edit_message_text(f"❌ Jobb `{job_id}` avbrutet.")


# ── Pipeline execution + response ──────────────────────────────────

async def _run_and_respond(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    request: PipelineRequest,
) -> None:
    """Send progress message, run pipeline, send results."""
    user_id = update.effective_user.id

    # Send initial progress message
    progress_msg = await update.message.reply_text(
        "🐾 *Banana Squad arbetar...*\n\n⏳ Startar pipeline...",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(request.job_id),
    )

    # Set up progress tracker
    tracker = ProgressTracker(
        bot=context.bot,
        chat_id=update.effective_chat.id,
        message_id=progress_msg.message_id,
        job_id=request.job_id,
    )
    await event_bus.subscribe(tracker.handle_event)

    try:
        result = await run_pipeline(request)

        # Remove progress tracker
        await event_bus.unsubscribe(tracker.handle_event)

        # Update progress message to final state
        if result.error:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_msg.message_id,
                text=f"❌ *Pipeline misslyckades*\n\n{result.error}",
                parse_mode="Markdown",
            )
            return

        # Send results as media group
        successful_images = [img for img in result.images if img.success and img.file_path]

        if successful_images:
            # Edit progress to "complete"
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_msg.message_id,
                text="✅ *Banana Squad klar!* Se resultat nedan. ⬇️",
                parse_mode="Markdown",
            )

            # Send images as media group (max 10 per group)
            media = []
            for img in successful_images:
                path = Path(img.file_path)
                if path.exists():
                    media.append(InputMediaPhoto(
                        media=open(str(path), "rb"),
                        caption=f"{img.variant_type.value}" if len(media) == 0 else None,
                    ))

            if media:
                await context.bot.send_media_group(
                    chat_id=update.effective_chat.id,
                    media=media,
                )

            # Send evaluation summary
            if result.evaluation and result.evaluation.evaluations:
                ranking_lines = ["🏆 *Utvärdering*\n"]
                for ev in result.evaluation.evaluations:
                    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(ev.rank, f"#{ev.rank}")
                    ranking_lines.append(
                        f"{medal} *{ev.variant_type.value}* — "
                        f"{ev.scores.total:.1f}/40\n"
                        f"  _{ev.review[:100]}_"
                    )

                if result.evaluation.summary:
                    ranking_lines.append(f"\n📋 {result.evaluation.summary}")

                await update.message.reply_text(
                    "\n".join(ranking_lines),
                    parse_mode="Markdown",
                    reply_markup=refinement_keyboard(request.job_id),
                )
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_msg.message_id,
                text="⚠️ Inga bilder genererades. Försök med en annan beskrivning.",
            )

    except Exception as e:
        logger.exception("Pipeline error for user %d", user_id)
        await event_bus.unsubscribe(tracker.handle_event)
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=progress_msg.message_id,
                text=f"❌ Ett fel uppstod: {str(e)[:200]}",
            )
        except Exception:
            pass

    finally:
        _active_jobs.pop(user_id, None)
