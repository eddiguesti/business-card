# TODO

- [x] Draft Claude prompt — create prompt to ask Claude to build Telegram bot (completed)
- [x] Provide optional follow-ups and usage notes (completed)
- [x] Add `TODO.md` to workspace (completed)
- [x] Implement Telegram bot:
  - [x] OCR image handling (`ocr.py` — Tesseract)
  - [x] Store contacts in DB (`database.py` — SQLite with duplicate detection)
  - [x] Send follow-up emails (`email_sender.py` — SMTP/STARTTLS)
  - [x] Confirm-before-send toggle (`CONFIRM_BEFORE_SEND` env var, inline keyboard)
- [x] Write README with setup & env examples
- [x] Add tests / manual test instructions (`tests/test_core.py`)

Notes:
- Use environment variables for secrets.
- Prefer Tesseract for OCR unless cloud OCR justified.
- Grok (`grok-2-latest` via xAI API) used for structured field extraction.

## Manual test checklist

1. Copy `.env.example` to `.env`, fill in all required values.
2. `pip install -r requirements.txt`
3. Start bot: `python bot.py`
4. In Telegram: send `/start` — should see welcome message.
5. Send a photo of a business card.
6. Verify extracted fields look correct in the reply.
7. Check `contacts.db` with `sqlite3 contacts.db "SELECT * FROM contacts;"`.
8. Verify follow-up email arrives in the inbox.
9. Set `CONFIRM_BEFORE_SEND=true`, resend the photo — confirm inline keyboard appears.

## Run unit tests

```bash
# Set dummy env vars so config.py doesn't raise on import
export TELEGRAM_TOKEN=x XAI_API_KEY=x SMTP_USER=x SMTP_PASSWORD=x
pytest tests/ -v
```
