"""Business card contact extraction using Grok vision (xAI).

Sends the raw image directly to Grok which reads the card AND extracts
structured fields in a single API call — no Tesseract OCR needed.
"""

import base64
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

_PROMPT = (
    "This is a photo of a business card. Read all the text on the card and "
    "return a single JSON object with these exact keys: "
    "name, email, phone, company, title, address, website, notes. "
    "email and phone must be JSON arrays (possibly empty). "
    "All other fields are strings or null. "
    "Trim whitespace from all values. "
    "Return only the JSON object — no markdown, no explanation."
)


def extract_contact(image_bytes: bytes) -> dict:
    """Send image to Grok vision; returns a structured contact dict."""
    image_b64 = base64.b64encode(image_bytes).decode()

    response = _client.chat.completions.create(
        model="grok-4-1-fast-non-reasoning",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": _PROMPT,
                    },
                ],
            }
        ],
        max_tokens=512,
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
