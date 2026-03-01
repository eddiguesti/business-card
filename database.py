"""SQLite contact storage with per-user isolation.

Each Telegram user registers once (/register email@jengu.ai).
All contacts are tagged with the owner's telegram_id so Chris and Edd
each see only their own cards.
"""

import json
import logging
import sqlite3
from typing import Optional

from config import DB_PATH

logger = logging.getLogger(__name__)


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                email         TEXT NOT NULL,
                display_name  TEXT,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_telegram_id INTEGER NOT NULL,
                name              TEXT,
                email             TEXT NOT NULL DEFAULT '[]',  -- JSON array
                phone             TEXT NOT NULL DEFAULT '[]',  -- JSON array
                company           TEXT,
                title             TEXT,
                address           TEXT,
                website           TEXT,
                notes             TEXT,
                created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_telegram_id) REFERENCES users(telegram_id)
            )
        """)
        conn.commit()
    logger.info("Database initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# User registry
# ---------------------------------------------------------------------------

def register_user(telegram_id: int, email: str, display_name: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, email, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                email = excluded.email,
                display_name = excluded.display_name
            """,
            (telegram_id, email, display_name),
        )
        conn.commit()
    logger.info("Registered user %s → %s", telegram_id, email)


def get_user(telegram_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def _encode(contact: dict) -> tuple:
    return (
        contact.get("name"),
        json.dumps(contact.get("email") or []),
        json.dumps(contact.get("phone") or []),
        contact.get("company"),
        contact.get("title"),
        contact.get("address"),
        contact.get("website"),
        contact.get("notes"),
    )


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["email"] = json.loads(d.get("email") or "[]")
    d["phone"] = json.loads(d.get("phone") or "[]")
    return d


def find_duplicate(contact: dict, owner_telegram_id: int) -> Optional[int]:
    """Return existing contact id matching within this owner's contacts."""
    with sqlite3.connect(DB_PATH) as conn:
        for email in contact.get("email") or []:
            row = conn.execute(
                "SELECT id FROM contacts WHERE owner_telegram_id = ? AND email LIKE ?",
                (owner_telegram_id, f'%"{email}"%'),
            ).fetchone()
            if row:
                return row[0]

        name = contact.get("name")
        company = contact.get("company")
        if name and company:
            row = conn.execute(
                "SELECT id FROM contacts WHERE owner_telegram_id = ? AND name = ? AND company = ?",
                (owner_telegram_id, name, company),
            ).fetchone()
            if row:
                return row[0]

    return None


def upsert_contact(contact: dict, owner_telegram_id: int) -> tuple[int, bool]:
    """Insert or merge contact for a specific owner. Returns (id, is_new)."""
    existing_id = find_duplicate(contact, owner_telegram_id)

    with sqlite3.connect(DB_PATH) as conn:
        if existing_id:
            name, email, phone, company, title, address, website, notes = _encode(contact)
            conn.execute(
                """
                UPDATE contacts SET
                    name    = COALESCE(?, name),
                    email   = COALESCE(NULLIF(?, '[]'), email),
                    phone   = COALESCE(NULLIF(?, '[]'), phone),
                    company = COALESCE(?, company),
                    title   = COALESCE(?, title),
                    address = COALESCE(?, address),
                    website = COALESCE(?, website),
                    notes   = COALESCE(?, notes),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (name, email, phone, company, title, address, website, notes, existing_id),
            )
            conn.commit()
            logger.info("Updated existing contact id=%s (owner=%s)", existing_id, owner_telegram_id)
            return existing_id, False
        else:
            cursor = conn.execute(
                """
                INSERT INTO contacts
                    (owner_telegram_id, name, email, phone, company, title, address, website, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_telegram_id, *_encode(contact)),
            )
            conn.commit()
            new_id = cursor.lastrowid
            logger.info("Inserted new contact id=%s (owner=%s)", new_id, owner_telegram_id)
            return new_id, True


def get_contact(contact_id: int) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
