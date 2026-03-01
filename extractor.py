"""Business card contact extraction using Azure Document Intelligence.

Uses the prebuilt-businessCard model via azure-ai-formrecognizer (v3.1 API)
with an API key — no IAM role assignment required.
"""

import logging

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from config import AZURE_DOC_INTEL_ENDPOINT, AZURE_DOC_INTEL_KEY

logger = logging.getLogger(__name__)


def _make_client() -> DocumentAnalysisClient:
    return DocumentAnalysisClient(
        endpoint=AZURE_DOC_INTEL_ENDPOINT,
        credential=AzureKeyCredential(AZURE_DOC_INTEL_KEY),
    )


def _field_str(field) -> str:
    """Get string value from a DocumentField, falling back to content."""
    if not field:
        return ""
    return (str(field.value) if field.value else field.content or "").strip()


def _array_strings(fields: dict, key: str) -> list[str]:
    """Return all non-empty string values from an array-type DocumentField."""
    field = fields.get(key)
    if not field or not field.value:
        return []
    return [v for item in field.value if (v := _field_str(item))]


def extract_contact(image_bytes: bytes) -> dict:
    """Analyse a business card image; returns a structured contact dict."""
    client = _make_client()

    poller = client.begin_analyze_document("prebuilt-businessCard", document=image_bytes)
    result = poller.result()

    if not result.documents:
        logger.warning("Document Intelligence found no business card in image")
        return {
            "name": None, "email": [], "phone": [],
            "company": None, "title": None, "address": None,
            "website": None, "notes": None,
        }

    fields = result.documents[0].fields or {}

    # ContactNames is an array of objects with FirstName / MiddleName / LastName sub-fields
    name = None
    cn_field = fields.get("ContactNames")
    if cn_field and cn_field.value:
        obj = cn_field.value[0].value or {}  # dict of sub-fields
        parts = [
            _field_str(obj.get(k))
            for k in ("FirstName", "MiddleName", "LastName")
            if _field_str(obj.get(k))
        ]
        name = " ".join(parts) or None

    emails = _array_strings(fields, "Emails")
    phones = (
        _array_strings(fields, "MobilePhones")
        + _array_strings(fields, "WorkPhones")
        + _array_strings(fields, "OtherPhones")
    )
    companies = _array_strings(fields, "CompanyNames")
    titles = _array_strings(fields, "JobTitles")
    addresses = _array_strings(fields, "Addresses")
    websites = _array_strings(fields, "Websites")

    contact = {
        "name": name,
        "email": emails,
        "phone": phones,
        "company": companies[0] if companies else None,
        "title": titles[0] if titles else None,
        "address": addresses[0] if addresses else None,
        "website": websites[0] if websites else None,
        "notes": None,
    }

    logger.info(
        "Extracted contact: name=%r, emails=%s",
        contact.get("name"),
        contact.get("email"),
    )
    return contact
