"""Business card contact extraction using Azure Document Intelligence.

Uses the prebuilt-businessCard model via azure-ai-formrecognizer (v3.1 API)
with an API key — no IAM role assignment required.
"""

import logging
import re

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from config import AZURE_DOC_INTEL_ENDPOINT, AZURE_DOC_INTEL_KEY

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _extract_domain(website: str) -> str:
    """Parse the domain (without www.) from a website string.

    Examples:
        "www.jengu.ai"      → "jengu.ai"
        "https://jengu.ai"  → "jengu.ai"
        "jengu.ai/about"    → "jengu.ai"
    """
    if not website:
        return ""
    # Strip scheme
    domain = re.sub(r"^https?://", "", website.strip().lower())
    # Strip path/query
    domain = domain.split("/")[0].split("?")[0]
    # Strip www.
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _domain_base(domain: str) -> str:
    """Return the domain without the TLD (e.g. 'jengu.ai' → 'jengu')."""
    parts = domain.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else domain


def _fix_email_domains(emails: list[str], website_domain: str) -> list[str]:
    """Correct email domains that look like OCR typos of the website domain.

    Strategy:
    - If the email's domain base name matches the website's domain base name
      (case-insensitive, e.g. 'jengu' == 'jengu') but the TLD differs
      (e.g. '.al' vs '.ai'), replace the email domain with the website domain.
    - Also re-extracts any email buried inside a garbled string (e.g.
      Azure DI sometimes returns "john@co .com" with a stray space).
    """
    if not website_domain or not emails:
        return emails

    site_base = _domain_base(website_domain)
    fixed = []
    for email in emails:
        # Attempt to re-parse in case there are embedded spaces or junk
        clean = "".join(email.split())  # strip all whitespace
        m = _EMAIL_RE.search(clean)
        email = m.group(0).lower() if m else email.lower()

        local, _, email_domain = email.rpartition("@")
        if not local:
            fixed.append(email)
            continue

        email_base = _domain_base(email_domain)
        if email_base == site_base and email_domain != website_domain:
            corrected = f"{local}@{website_domain}"
            logger.info(
                "Corrected email domain: %s → %s (website: %s)",
                email, corrected, website_domain,
            )
            fixed.append(corrected)
        else:
            fixed.append(email)
    return fixed


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

    # Use the website as ground truth to fix OCR typos in email domains
    # (e.g. "jengu.al" → "jengu.ai" when website is "www.jengu.ai")
    website_domain = _extract_domain(websites[0]) if websites else ""
    emails = _fix_email_domains(emails, website_domain)

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
