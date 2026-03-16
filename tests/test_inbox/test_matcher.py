"""Tests for emplaiyed.inbox.matcher — plus-tag only matching."""

from __future__ import annotations

from datetime import datetime

import pytest

from emplaiyed.core.database import save_application, save_opportunity
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
from emplaiyed.inbox.matcher import (
    _extract_plus_tag,
    match_email_to_application,
)


# ---------------------------------------------------------------------------
# Unit tests for plus-tag extraction
# ---------------------------------------------------------------------------


class TestExtractPlusTag:
    def test_standard(self):
        assert _extract_plus_tag("moi+r8dZcf@jpelletier.org") == "r8dZcf"

    def test_longer_tag(self):
        assert _extract_plus_tag("moi+AbCd1234@example.com") == "AbCd1234"

    def test_no_tag(self):
        assert _extract_plus_tag("moi@jpelletier.org") is None

    def test_empty(self):
        assert _extract_plus_tag("") is None

    def test_short_tag_ignored(self):
        """Tags shorter than 4 chars are not matched (too ambiguous)."""
        assert _extract_plus_tag("moi+ab@example.com") is None

    def test_tag_too_long_ignored(self):
        """Tags longer than 10 chars are not matched."""
        assert _extract_plus_tag("moi+abcdefghijk@example.com") is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_opp(short_id: str = "tEsT01", company: str = "Acme Corp") -> Opportunity:
    return Opportunity(
        id=f"opp-{short_id}",
        short_id=short_id,
        source="test",
        company=company,
        title="Developer",
        description="Test job",
        scraped_at=datetime.now(),
    )


def _make_app(opp_id: str) -> Application:
    return Application(
        id=f"app-{opp_id}",
        opportunity_id=opp_id,
        status=ApplicationStatus.OUTREACH_SENT,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Integration tests with DB
# ---------------------------------------------------------------------------


class TestMatchEmailToApplication:
    def test_plus_tag_match(self, db):
        """Plus-address tag matches the correct opportunity."""
        opp = _make_opp(short_id="xY3kLm")
        save_opportunity(db, opp)
        app = _make_app(opp.id)
        save_application(db, app)

        result = match_email_to_application(
            db,
            to_address="moi+xY3kLm@jpelletier.org",
        )
        assert result is not None
        assert result.match_tier == "plus_tag"
        assert result.opportunity.id == opp.id
        assert result.application.id == app.id

    def test_unknown_tag_returns_none(self, db):
        """A plus-tag that doesn't match any opportunity returns None."""
        opp = _make_opp(short_id="xY3kLm")
        save_opportunity(db, opp)
        app = _make_app(opp.id)
        save_application(db, app)

        result = match_email_to_application(
            db,
            to_address="moi+ZZZZZZ@jpelletier.org",
        )
        assert result is None

    def test_no_tag_returns_none(self, db):
        """Email without a plus-tag returns None."""
        opp = _make_opp()
        save_opportunity(db, opp)
        app = _make_app(opp.id)
        save_application(db, app)

        result = match_email_to_application(
            db,
            to_address="moi@jpelletier.org",
        )
        assert result is None

    def test_empty_to_address_returns_none(self, db):
        result = match_email_to_application(db, to_address="")
        assert result is None

    def test_tag_matches_opp_but_no_application(self, db):
        """If the opportunity exists but has no application, return None."""
        opp = _make_opp(short_id="aBcDeF")
        save_opportunity(db, opp)
        # No application saved

        result = match_email_to_application(
            db,
            to_address="moi+aBcDeF@jpelletier.org",
        )
        assert result is None

    def test_multiple_opps_correct_match(self, db):
        """With multiple opportunities, the plus-tag picks the right one."""
        opp1 = _make_opp(short_id="aaa111", company="Acme")
        opp2 = _make_opp(short_id="bbb222", company="Google")
        save_opportunity(db, opp1)
        save_opportunity(db, opp2)
        app1 = _make_app(opp1.id)
        app2 = _make_app(opp2.id)
        save_application(db, app1)
        save_application(db, app2)

        result = match_email_to_application(
            db,
            to_address="moi+bbb222@jpelletier.org",
        )
        assert result is not None
        assert result.opportunity.company == "Google"
        assert result.application.id == app2.id

    def test_no_applications_in_db(self, db):
        """Empty DB returns None."""
        result = match_email_to_application(
            db,
            to_address="moi+xY3kLm@jpelletier.org",
        )
        assert result is None
