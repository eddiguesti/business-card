"""Structured contact extraction from OCR text using Grok (xAI).

Design note: Tesseract gives us raw text cheaply; Grok handles the messy
field-parsing work that regex would get wrong (e.g. multi-line addresses,
phone format variations, LinkedIn vs website distinction).

Grok exposes an OpenAI-compatible API so we use the openai SDK pointed at
https://api.x.ai/v1.
"""

import json
import logging
import re

from openai import OpenAI

from config import XAI_API_KEY

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1",
)

_SYSTEM = (
    "You are a contact-data extractor. Given raw OCR text from a business card, "
    "return a single JSON object with these exact keys: "
    "name, email, phone, company, title, address, website, notes. "
    "email and phone must be JSON arrays (possibly empty). "
    "All other fields are strings or null. "
    "Sanitize values: trim whitespace, normalise phone numbers to E.164 where possible. "
    "Return only the JSON object — no markdown, no explanation."
)


def extract_contact(ocr_text: str) -> dict:
    """Parse OCR text into a structured contact dict via Grok."""
    response = _client.chat.completions.create(
        model="grok-4-1-fast-reasoning",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": ocr_text},
        ],
        max_tokens=512,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Strip accidental markdown code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        contact = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Grok returned non-JSON: %s", raw[:200])
        raise ValueError("Failed to parse contact JSON from Grok response") from exc

    # Ensure list fields are actually lists
    for field in ("email", "phone"):
        if not isinstance(contact.get(field), list):
            contact[field] = [contact[field]] if contact.get(field) else []

    logger.info(
        "Extracted contact: name=%r, emails=%s",
        contact.get("name"),
        contact.get("email"),
    )
    return contact
