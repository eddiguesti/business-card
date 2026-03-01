# Business Card Bot

A minimal Telegram bot that automates business-card intake and follow-up.

Send a photo of a business card → it extracts the contact, stores it in SQLite, and sends a follow-up email.

---

## Stack & design decisions

| Concern | Choice | Why |
|---|---|---|
| Bot framework | `python-telegram-bot` v21 | Async, well-maintained, idiomatic |
| OCR | Tesseract via `pytesseract` | Open-source, no cloud dependency, free |
| Field extraction | Grok (`grok-2-latest`) via xAI API | Handles messy OCR output far better than regex |
| Database | SQLite (`sqlite3` built-in) | Zero infrastructure, single-user friendly; swap for Postgres if needed |
| Email delivery | SMTP + STARTTLS | Works with Gmail, Outlook, SendGrid, Mailgun — no extra SDK |

---

## Prerequisites

- Python 3.11+
- Tesseract OCR installed on the host:
  - macOS: `brew install tesseract`
  - Ubuntu/Debian: `sudo apt install tesseract-ocr`
  - Windows: [installer](https://github.com/UB-Mannheim/tesseract/wiki)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An [xAI API key](https://console.x.ai/)
- SMTP credentials (Gmail app password, SendGrid, etc.)

---

## Setup

```bash
# 1. Clone / copy the project
cd "business cards automation"

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_TOKEN` | yes | — | Bot token from BotFather |
| `XAI_API_KEY` | yes | — | xAI API key for Grok |
| `SMTP_HOST` | yes | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | no | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | yes | — | SMTP login username |
| `SMTP_PASSWORD` | yes | — | SMTP password / app password |
| `FROM_EMAIL` | no | `SMTP_USER` | Sender address |
| `DB_PATH` | no | `contacts.db` | Path to SQLite database |
| `CONFIRM_BEFORE_SEND` | no | `false` | Set `true` to approve each email |
| `FOLLOW_UP_SUBJECT` | no | `Great meeting you!` | Email subject line |
| `FOLLOW_UP_TEMPLATE` | no | (see `.env.example`) | Email body (`{name}`, `{company}`, `{title}` available) |

### Gmail setup

1. Enable 2-Step Verification on your Google account.
2. Go to **Google Account → Security → App passwords**.
3. Generate an app password and use it as `SMTP_PASSWORD`.

---

## Running locally

```bash
python bot.py
```

The bot will poll Telegram for updates. Press `Ctrl+C` to stop.

---

## Deploying

Any always-on Linux host works. Example with `systemd`:

```ini
# /etc/systemd/system/bizcard-bot.service
[Unit]
Description=Business Card Bot
After=network.target

[Service]
WorkingDirectory=/opt/bizcard-bot
EnvironmentFile=/opt/bizcard-bot/.env
ExecStart=/opt/bizcard-bot/.venv/bin/python bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bizcard-bot
```

---

## Security & privacy

- All secrets are in environment variables — never hard-coded.
- Raw images are never written to disk; they are processed in-memory and discarded.
- SQLite file permissions default to the process owner; restrict with `chmod 600 contacts.db`.
- SMTP uses STARTTLS — credentials are not sent in plaintext.
- Input from OCR is passed only to Grok for parsing; it is not logged at INFO level.

---

## Project structure

```
.
├── bot.py           # Telegram handlers & entry point
├── ocr.py           # Tesseract OCR wrapper
├── extractor.py     # Grok-based field extraction
├── database.py      # SQLite contact storage
├── email_sender.py  # SMTP follow-up email
├── config.py        # Environment variable loading
├── requirements.txt
├── .env.example
└── tests/
    └── test_core.py
```
