"""Business Card Bot — main entry point.

Multi-user flow:
  1. Each user registers once: /register chris@jengu.ai
  2. User sends a photo → Grok vision extracts contact → DB upsert (tagged to owner)
  3. Follow-up email sent from the owner's @jengu.ai address via Azure Graph
"""

import csv
import io
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from database import get_contacts, get_user, init_db, register_user, upsert_contact
from email_sender import send_follow_up
from extractor import extract_contact

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Contacts waiting for confirm/skip button {user_id: contact_dict}
_pending: dict[int, dict] = {}
# Contacts waiting for the user to type an email address {user_id: contact_dict}
_awaiting_email: dict[int, dict] = {}


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
    else:
        lines.append("Email:   (none found)")
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
        return "No email address — skipped."
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


async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /contacts — list all your saved contacts."""
    telegram_user = update.effective_user
    user = _get_registered_user(telegram_user.id)
    if not user:
        await update.message.reply_text("You need to register first:\n  /register your@jengu.ai")
        return

    contacts = get_contacts(telegram_user.id)
    if not contacts:
        await update.message.reply_text("No contacts saved yet — send a business card photo to get started.")
        return

    lines = [f"Your contacts ({len(contacts)}):\n"]
    for c in contacts:
        name = c.get("name") or "Unknown"
        email = c["email"][0] if c.get("email") else "no email"
        company = f" — {c['company']}" if c.get("company") else ""
        lines.append(f"• {name}{company}\n  {email}")

    await update.message.reply_text("\n".join(lines))


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /export — download all your contacts as a CSV file."""
    telegram_user = update.effective_user
    user = _get_registered_user(telegram_user.id)
    if not user:
        await update.message.reply_text("You need to register first:\n  /register your@jengu.ai")
        return

    contacts = get_contacts(telegram_user.id)
    if not contacts:
        await update.message.reply_text("No contacts saved yet.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Email", "Phone", "Company", "Title", "Website", "Address", "Saved At"])
    for c in contacts:
        writer.writerow([
            c.get("name") or "",
            ", ".join(c.get("email") or []),
            ", ".join(c.get("phone") or []),
            c.get("company") or "",
            c.get("title") or "",
            c.get("website") or "",
            c.get("address") or "",
            c.get("created_at") or "",
        ])

    file_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
    file_bytes.name = f"contacts_{user['email'].split('@')[0]}.csv"
    await update.message.reply_document(document=file_bytes, filename=file_bytes.name,
                                        caption=f"{len(contacts)} contacts exported.")


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
    has_email = bool(contact.get("email"))

    _pending[telegram_user.id] = contact

    if not has_email:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Enter email manually", callback_data="enter_email")],
            [
                InlineKeyboardButton("✓ Save without email", callback_data="skip_send"),
                InlineKeyboardButton("✗ Discard", callback_data="discard_contact"),
            ],
        ])
        await update.message.reply_text(
            f"{summary}\n\nDo these details look correct?\n(No email found on card)",
            reply_markup=keyboard,
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✓ Correct — Save & Send follow-up", callback_data="confirm_send")],
            [
                InlineKeyboardButton("Save, skip email", callback_data="skip_send"),
                InlineKeyboardButton("✗ Discard", callback_data="discard_contact"),
            ],
        ])
        await update.message.reply_text(
            f"{summary}\n\nDo these details look correct?",
            reply_markup=keyboard,
        )


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    telegram_user = update.effective_user
    user = _get_registered_user(telegram_user.id)
    contact = _pending.pop(telegram_user.id, None)

    if not contact:
        await query.edit_message_text("Session expired — please resend the photo.")
        return

    if query.data == "discard_contact":
        await query.edit_message_text("Contact discarded — nothing saved.")
        return

    if query.data == "enter_email":
        # Move contact to awaiting-email state without saving to DB yet
        _awaiting_email[telegram_user.id] = contact
        await query.edit_message_text(
            f"{_format_contact(contact)}\n\nType the email address to send the follow-up to:"
        )
        return

    contact_id, is_new = upsert_contact(contact, owner_telegram_id=telegram_user.id)
    db_status = "New contact saved" if is_new else "Existing contact updated"

    if query.data == "confirm_send" and user:
        email_status = _do_send(contact, from_email=user["email"], from_name=user["display_name"])
        await query.edit_message_text(f"{db_status}. {email_status}")
    else:
        await query.edit_message_text(f"{db_status}. Email skipped.")


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the manual email address typed by the user after 'Enter email manually'."""
    telegram_user = update.effective_user
    contact = _awaiting_email.get(telegram_user.id)

    if not contact:
        return  # Not in email-input state — ignore the text

    # Extract email from whatever the user typed (e.g. "his email is john@co.com" works)
    match = _EMAIL_RE.search(update.message.text)
    if not match:
        await update.message.reply_text(
            "Couldn't find an email address in that. Please type it again:"
        )
        return

    email = match.group(0).lower()
    _awaiting_email.pop(telegram_user.id)
    contact["email"] = [email]

    user = _get_registered_user(telegram_user.id)
    contact_id, is_new = upsert_contact(contact, owner_telegram_id=telegram_user.id)
    db_status = "New contact saved" if is_new else "Existing contact updated"
    email_status = _do_send(contact, from_email=user["email"], from_name=user["display_name"])
    await update.message.reply_text(f"{db_status}. {email_status}")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Suppress expected 409 Conflict during deployments; log everything else."""
    if isinstance(context.error, Conflict):
        logger.warning("Telegram 409 conflict (deployment overlap) — will recover automatically.")
        return
    logger.error("Unhandled error", exc_info=context.error)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    init_db()

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_handler(CallbackQueryHandler(
        handle_confirm, pattern=r"^(confirm|skip)_send$|^enter_email$|^discard_contact$"
    ))
    app.add_error_handler(handle_error)

    logger.info("Bot polling — confirmation always required before saving")
    app.run_polling()


if __name__ == "__main__":
    main()
