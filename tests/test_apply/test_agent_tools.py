"""Tests for inbox agent tools."""

from __future__ import annotations

import json

from emplaiyed.inbox.agent_tools import _email_to_dict
from emplaiyed.inbox.fetcher import FetchedEmail
from datetime import datetime


class TestEmailToDict:
    def test_basic_serialization(self):
        em = FetchedEmail(
            message_id="<abc@example.com>",
            from_address="login@indeed.com",
            from_name="Indeed",
            to_address="moi@jpelletier.org",
            subject="Sign in to Indeed with code: 188946",
            date=datetime(2026, 3, 18, 16, 55, 34),
            body_text="Your Indeed code is 188946.",
            raw_headers={
                "from": "Indeed <login@indeed.com>",
                "to": "moi@jpelletier.org",
                "reply-to": "",
                "delivered-to": "moi@jpelletier.org",
                "return-path": "<bounces+moi=jpelletier.org@em724.indeed.com>",
                "x-original-to": "",
            },
        )
        d = _email_to_dict(em)
        assert d["from_address"] == "login@indeed.com"
        assert d["subject"] == "Sign in to Indeed with code: 188946"
        assert d["body_text"] == "Your Indeed code is 188946."
        assert d["date"] == "2026-03-18T16:55:34"
        assert d["headers"]["delivered_to"] == "moi@jpelletier.org"
        assert "bounces" in d["headers"]["return_path"]

    def test_none_date(self):
        em = FetchedEmail(
            message_id="<x>",
            from_address="a@b.com",
            from_name="A",
            to_address="c@d.com",
            subject="Test",
            date=None,
            body_text="body",
        )
        d = _email_to_dict(em)
        assert d["date"] is None

    def test_json_serializable(self):
        em = FetchedEmail(
            message_id="<x>",
            from_address="a@b.com",
            from_name="A",
            to_address="c@d.com",
            subject="Test",
            date=datetime(2026, 1, 1),
            body_text="body",
            raw_headers={
                "delivered-to": "c@d.com",
                "return-path": "<a@b.com>",
            },
        )
        d = _email_to_dict(em)
        s = json.dumps(d, ensure_ascii=False)
        assert '"from_address": "a@b.com"' in s
