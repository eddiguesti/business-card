"""Business Card Bot — main entry point.

Multi-user flow:
  1. Each user registers once: /register chris@jengu.ai
  2. User sends a photo → OCR → Grok extraction → DB upsert (tagged to owner)
  3. Follow-up email sent from the owner's @jengu.ai address via Azure Graph
"""

import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from database import get_user, init_db, register_user, upsert_contact
from email_sender import send_follow_up
from extractor import extract_contact

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Pending contacts awaiting confirmation {user_id: contact_dict}
_pending: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_contact(c: dict) -> str:
    lines: list[str] = []
    if c.get("name"):
        lines.append(f"Name:    {c['name']}")
    if c.get("title"):
        lines.append(f"Title:   {c['title']}")
    if c.get("company"):
        lines.append(f"Company: {c['company']}")
    if c.get("email"):
        lines.append(f"Email:   {', '.join(c['email'])}")
    if c.get("phone"):
        lines.append(f"Phone:   {', '.join(c['phone'])}")
    if c.get("website"):
        lines.append(f"Web:     {c['website']}")
    if c.get("address"):
        lines.append(f"Address: {c['address']}")
    if c.get("notes"):
        lines.append(f"Notes:   {c['notes']}")
    return "\n".join(lines) if lines else "No contact info extracted."


def _do_send(contact: dict, from_email: str, from_name: str) -> str:
    emails = contact.get("email") or []
    if not emails:
        return "No email address found — skipped."
    sent = send_follow_up(contact, from_email=from_email, from_name=from_name)
    return f"Follow-up sent to {emails[0]}." if sent else f"Email to {emails[0]} failed."


def _get_registered_user(telegram_id: int) -> dict | None:
    return get_user(telegram_id)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = _get_registered_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"Welcome back, {user['display_name']}!\n"
            f"Sending as: {user['email']}\n\n"
            "Send me a business card photo to get started."
        )
    else:
        await update.message.reply_text(
            "Business Card Bot\n\n"
            "Register first with your @jengu.ai email:\n"
            "  /register edd@jengu.ai"
        )


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /register email@jengu.ai"""
    telegram_user = update.effective_user
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /register your@jengu.ai")
        return

    email = args[0].strip().lower()

    if not email.endswith(f"@{config.ALLOWED_DOMAIN}"):
        await update.message.reply_text(
            f"Only @{config.ALLOWED_DOMAIN} addresses are allowed."
        )
        return

    display_name = telegram_user.full_name or email.split("@")[0]
    register_user(telegram_user.id, email, display_name)

    await update.message.reply_text(
        f"Registered! Follow-up emails will be sent from {email}.\n\n"
        "Send me a photo of a business card."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_user = update.effective_user
    user = _get_registered_user(telegram_user.id)

    if not user:
        await update.message.reply_text(
            "You need to register first:\n  /register your@jengu.ai"
        )
        return

    await update.message.reply_text("Processing...")

    # Download highest-resolution photo
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    image_bytes = buf.getvalue()

    # Extract contact directly from image via Grok vision (single API call)
    try:
        contact = extract_contact(image_bytes)
    except Exception as exc:
        logger.error("Extraction failed: %s", exc)
        await update.message.reply_text("Could not extract contact info. Please try again.")
        return

    summary = _format_contact(contact)

    if config.CONFIRM_BEFORE_SEND:
        _pending[telegram_user.id] = contact
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Send email", callback_data="confirm_send"),
                InlineKeyboardButton("Skip email", callback_data="skip_send"),
            ]
        ])
        await update.message.reply_text(
            f"{summary}\n\nSend follow-up from {user['email']}?",
            reply_markup=keyboard,
        )
    else:
        contact_id, is_new = upsert_contact(contact, owner_telegram_id=telegram_user.id)
        db_status = "New contact saved" if is_new else "Existing contact updated"
        email_status = _do_send(contact, from_email=user["email"], from_name=user["display_name"])
        await update.message.reply_text(f"{summary}\n\n{db_status}. {email_status}")


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    telegram_user = update.effective_user
    user = _get_registered_user(telegram_user.id)
    contact = _pending.pop(telegram_user.id, None)

    if not contact:
        await query.edit_message_text("Session expired — please resend the photo.")
        return

    contact_id, is_new = upsert_contact(contact, owner_telegram_id=telegram_user.id)
    db_status = "New contact saved" if is_new else "Existing contact updated"

    if query.data == "confirm_send" and user:
        email_status = _do_send(contact, from_email=user["email"], from_name=user["display_name"])
        await query.edit_message_text(f"{db_status}. {email_status}")
    else:
        await query.edit_message_text(f"{db_status}. Email skipped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    init_db()

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_confirm, pattern=r"^(confirm|skip)_send$"))

    logger.info("Bot polling (CONFIRM_BEFORE_SEND=%s)", config.CONFIRM_BEFORE_SEND)
    app.run_polling()


if __name__ == "__main__":
    main()
