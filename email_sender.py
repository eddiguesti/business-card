"""Email delivery via Microsoft Azure Graph API.

Uses the same Azure app registration as the marketing-agent project.
The app needs Mail.Send application permission on the tenant so it can
send on behalf of any @jengu.ai mailbox.

Per-user HTML signatures are loaded from signatures/{email}.html if present.
"""

import logging
import os

import msal
import requests

from config import AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, FOLLOW_UP_SUBJECT, FOLLOW_UP_TEMPLATE

logger = logging.getLogger(__name__)

_GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
_SEND_MAIL_URL = "https://graph.microsoft.com/v1.0/users/{from_email}/sendMail"

_SIGNATURES_DIR = os.path.join(os.path.dirname(__file__), "signatures")


def _load_signature(from_email: str) -> str:
    """Return HTML signature for this sender, or empty string if none."""
    path = os.path.join(_SIGNATURES_DIR, f"{from_email}.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def _get_access_token() -> str:
    app = msal.ConfidentialClientApplication(
        client_id=AZURE_CLIENT_ID,
        client_credential=AZURE_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{AZURE_TENANT_ID}",
    )
    result = app.acquire_token_for_client(scopes=_GRAPH_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"MSAL token error: {result.get('error_description', result)}")
    return result["access_token"]


def send_follow_up(contact: dict, from_email: str, from_name: str) -> bool:
    """Send a follow-up email to the first address in contact['email'].

    Args:
        contact:    Extracted contact dict.
        from_email: Sender's @jengu.ai address (per-user).
        from_name:  Sender's display name.

    Returns True on success, False on failure (never raises).
    """
    emails: list[str] = contact.get("email") or []
    if not emails:
        logger.warning("No email address for contact %r — skipping send", contact.get("name"))
        return False

    to_address = emails[0]

    # Use first name only; omit name entirely if not available
    name_parts = (contact.get("name") or "").strip().split()
    first_name = name_parts[0] if name_parts else ""
    greeting = f"Hi {first_name}," if first_name else "Hi,"

    plain_body = greeting + "\n\n" + FOLLOW_UP_TEMPLATE.format(
        first_name=first_name,
        company=contact.get("company") or "",
        title=contact.get("title") or "",
    )

    # Convert plain text to styled HTML paragraphs, auto-linking any URLs, then append signature
    import re as _re
    _url_re = _re.compile(r'(https?://\S+)')

    _LINK_STYLE = "color:#054E88;text-decoration:none;font-weight:500;"
    _P_STYLE = "margin:0 0 14px 0;"

    paragraphs = []
    for line in plain_body.splitlines():
        if not line.strip():
            paragraphs.append(f'<p style="{_P_STYLE}">&nbsp;</p>')
        else:
            linked = _url_re.sub(
                rf'<a href="\1" target="_blank" style="{_LINK_STYLE}">\1</a>', line
            )
            paragraphs.append(f'<p style="{_P_STYLE}">{linked}</p>')

    html_body = (
        '<div style="'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;"
        "font-size:15px;line-height:1.65;color:#1a1a1a;max-width:600px;"
        '">'
        + "".join(paragraphs)
        + "</div>"
    )
    html_body += _load_signature(from_email)

    payload = {
        "message": {
            "subject": FOLLOW_UP_SUBJECT,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": to_address}}],
            "from": {"emailAddress": {"name": from_name, "address": from_email}},
        },
        "saveToSentItems": True,
    }

    try:
        token = _get_access_token()
        url = _SEND_MAIL_URL.format(from_email=from_email)
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Follow-up sent to %s from %s", to_address, from_email)
        return True
    except requests.HTTPError as exc:
        logger.error("Graph API error sending to %s: %s — %s", to_address, exc, exc.response.text[:200])
        return False
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_address, exc)
        return False
