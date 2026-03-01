import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required environment variable {key!r} is not set")
    return val


TELEGRAM_TOKEN = _require("TELEGRAM_TOKEN")

# Azure AD app (shared by email sending and Document Intelligence)
AZURE_TENANT_ID = _require("AZURE_TENANT_ID")
AZURE_CLIENT_ID = _require("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = _require("AZURE_CLIENT_SECRET")

# Azure Document Intelligence endpoint (e.g. https://xxx.cognitiveservices.azure.com/)
AZURE_DOC_INTEL_ENDPOINT = _require("AZURE_DOC_INTEL_ENDPOINT")

# Only this domain may register and use the bot
ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "jengu.ai")

DB_PATH = os.getenv("DB_PATH", "contacts.db")

# Set to "true" to require user confirmation before sending follow-up emails.
# Default: auto-send.
CONFIRM_BEFORE_SEND = os.getenv("CONFIRM_BEFORE_SEND", "false").lower() == "true"

FOLLOW_UP_SUBJECT = os.getenv("FOLLOW_UP_SUBJECT", "Great meeting you at ITB Berlin!")
FOLLOW_UP_TEMPLATE = os.getenv("FOLLOW_UP_TEMPLATE") or (
    "Just dropping this over so you have my details — great meeting you at ITB!\n\n"
    "Just to recap what we do: we build custom AI solutions and software tailored to each business. "
    "Every client is different, but most of the companies we work with end up saving hundreds of hours a week in operations.\n\n"
    "The biggest wins we tend to see in hospitality are around guest enquiries, "
    "repetitive admin, and back-of-house scheduling — but we always take the time "
    "to understand your setup first and find where AI can make the biggest difference for you specifically.\n\n"
    "In the meantime, if you want a quick sense of the potential impact for your business, "
    "we have a calculator here: https://www.jengu.ai/mobile-calculator.html\n\n"
    "Happy to jump on a quick call if you'd like to explore it further — "
    "book a time using the link in my signature.\n\n"
    "Best,"
)
