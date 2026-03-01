"""Unit tests for database, extractor helpers, and email logic.

Run with:
    cd "business cards automation"
    TELEGRAM_TOKEN=x XAI_API_KEY=x AZURE_TENANT_ID=x AZURE_CLIENT_ID=x AZURE_CLIENT_SECRET=x \
        .venv/bin/pytest tests/ -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# database.py
# ---------------------------------------------------------------------------

class TestDatabase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()

        import config as cfg
        self._orig_db = cfg.DB_PATH
        cfg.DB_PATH = self._tmp.name

        import importlib, database
        importlib.reload(database)
        self.db = database
        self.db.init_db()

        # Register a test user
        self.db.register_user(1001, "edd@jengu.ai", "Edd")
        self.db.register_user(1002, "chris@jengu.ai", "Chris")

    def tearDown(self):
        import config as cfg
        cfg.DB_PATH = self._orig_db
        os.unlink(self._tmp.name)

    def _contact(self, name="Alice Smith", email=None, company="Acme"):
        return {
            "name": name,
            "email": email or ["alice@example.com"],
            "phone": ["+1-555-0100"],
            "company": company,
            "title": "Engineer",
            "address": "123 Main St",
            "website": "acme.com",
            "notes": None,
        }

    def test_insert_new_contact(self):
        cid, is_new = self.db.upsert_contact(self._contact(), owner_telegram_id=1001)
        self.assertTrue(is_new)
        self.assertGreater(cid, 0)

    def test_duplicate_by_email_same_owner(self):
        c = self._contact()
        cid1, _ = self.db.upsert_contact(c, owner_telegram_id=1001)
        cid2, is_new = self.db.upsert_contact(c, owner_telegram_id=1001)
        self.assertFalse(is_new)
        self.assertEqual(cid1, cid2)

    def test_same_card_different_owners_are_separate(self):
        c = self._contact()
        cid1, new1 = self.db.upsert_contact(c, owner_telegram_id=1001)
        cid2, new2 = self.db.upsert_contact(c, owner_telegram_id=1002)
        self.assertTrue(new1)
        self.assertTrue(new2)
        self.assertNotEqual(cid1, cid2)

    def test_duplicate_by_name_company(self):
        c1 = self._contact(email=["a@example.com"])
        c2 = self._contact(email=["b@example.com"])
        cid1, _ = self.db.upsert_contact(c1, owner_telegram_id=1001)
        cid2, is_new = self.db.upsert_contact(c2, owner_telegram_id=1001)
        self.assertFalse(is_new)
        self.assertEqual(cid1, cid2)

    def test_get_contact_round_trips_lists(self):
        cid, _ = self.db.upsert_contact(self._contact(), owner_telegram_id=1001)
        result = self.db.get_contact(cid)
        self.assertIsInstance(result["email"], list)
        self.assertIsInstance(result["phone"], list)
        self.assertEqual(result["email"], ["alice@example.com"])

    def test_get_user(self):
        user = self.db.get_user(1001)
        self.assertEqual(user["email"], "edd@jengu.ai")
        self.assertIsNone(self.db.get_user(9999))


# ---------------------------------------------------------------------------
# extractor.py — JSON cleanup logic
# ---------------------------------------------------------------------------

class TestExtractorCleanup(unittest.TestCase):

    def _run_cleanup(self, raw: str) -> dict:
        import re
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        contact = json.loads(raw.strip())
        for field in ("email", "phone"):
            if not isinstance(contact.get(field), list):
                contact[field] = [contact[field]] if contact.get(field) else []
        return contact

    def test_plain_json(self):
        raw = '{"name":"Bob","email":["b@x.com"],"phone":[],"company":null,"title":null,"address":null,"website":null,"notes":null}'
        self.assertEqual(self._run_cleanup(raw)["name"], "Bob")

    def test_strips_markdown_fences(self):
        raw = '```json\n{"name":"Bob","email":[],"phone":[],"company":null,"title":null,"address":null,"website":null,"notes":null}\n```'
        self.assertEqual(self._run_cleanup(raw)["name"], "Bob")

    def test_coerces_string_email_to_list(self):
        raw = '{"name":"Bob","email":"b@x.com","phone":[],"company":null,"title":null,"address":null,"website":null,"notes":null}'
        c = self._run_cleanup(raw)
        self.assertIsInstance(c["email"], list)

    def test_null_email_becomes_empty_list(self):
        raw = '{"name":"Bob","email":null,"phone":null,"company":null,"title":null,"address":null,"website":null,"notes":null}'
        c = self._run_cleanup(raw)
        self.assertEqual(c["email"], [])
        self.assertEqual(c["phone"], [])


# ---------------------------------------------------------------------------
# email_sender.py — Azure Graph
# ---------------------------------------------------------------------------

class TestEmailSender(unittest.TestCase):

    def test_no_email_returns_false(self):
        from email_sender import send_follow_up
        result = send_follow_up({"name": "Nobody", "email": []}, "edd@jengu.ai", "Edd")
        self.assertFalse(result)

    @patch("email_sender._get_access_token", return_value="fake-token")
    @patch("email_sender.requests.post")
    def test_sends_successfully(self, mock_post, _mock_token):
        mock_post.return_value = MagicMock(status_code=202)
        mock_post.return_value.raise_for_status = MagicMock()

        from email_sender import send_follow_up
        result = send_follow_up(
            {"name": "Alice", "email": ["alice@example.com"]},
            from_email="edd@jengu.ai",
            from_name="Edd",
        )
        self.assertTrue(result)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertIn("edd@jengu.ai", call_kwargs[0][0])  # URL contains from_email

    @patch("email_sender._get_access_token", side_effect=RuntimeError("auth failed"))
    def test_token_error_returns_false(self, _):
        from email_sender import send_follow_up
        result = send_follow_up(
            {"name": "Alice", "email": ["alice@example.com"]},
            from_email="edd@jengu.ai",
            from_name="Edd",
        )
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# bot.py helpers
# ---------------------------------------------------------------------------

class TestFormatContact(unittest.TestCase):

    def _format(self, c):
        from bot import _format_contact
        return _format_contact(c)

    def test_full_contact(self):
        c = {
            "name": "Jane Doe", "title": "CEO", "company": "Acme",
            "email": ["jane@acme.com"], "phone": ["+1-555-0200"],
            "website": "acme.com", "address": "1 Corp Way", "notes": "Met at conf",
        }
        out = self._format(c)
        self.assertIn("Jane Doe", out)
        self.assertIn("jane@acme.com", out)

    def test_empty_contact(self):
        self.assertEqual(self._format({}), "No contact info extracted.")


if __name__ == "__main__":
    unittest.main()
