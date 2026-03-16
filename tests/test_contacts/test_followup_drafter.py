"""Tests for contact-aware follow-up content generation."""

from __future__ import annotations

from datetime import datetime

from pydantic_ai.models.test import TestModel

from emplaiyed.contacts.followup_drafter import (
    FollowUpContent,
    _build_followup_prompt,
    draft_contact_followup,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Contact,
    Opportunity,
    Profile,
)


def _test_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python", "FastAPI", "SQL"],
    )


def _test_opportunity() -> Opportunity:
    return Opportunity(
        source="talent",
        company="Acme Corp",
        title="Backend Developer",
        description="We need a Python backend developer with FastAPI experience.",
        scraped_at=datetime.now(),
    )


def _test_application() -> Application:
    return Application(
        opportunity_id="opp-123",
        status=ApplicationStatus.FOLLOW_UP_PENDING,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _test_contact() -> Contact:
    return Contact(
        opportunity_id="opp-123",
        name="Jane Recruiter",
        email="jane@acme.com",
        title="Recruiter",
        source="json_ld",
        confidence=0.9,
    )


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildFollowupPrompt:
    def test_with_contact(self):
        prompt = _build_followup_prompt(
            _test_profile(),
            _test_opportunity(),
            _test_contact(),
            _test_application(),
            followup_number=1,
            days_since=5,
        )
        assert "Acme Corp" in prompt
        assert "Backend Developer" in prompt
        assert "Jane Recruiter" in prompt
        assert "jane@acme.com" in prompt
        assert "Recruiter" in prompt
        assert "first" in prompt

    def test_without_contact(self):
        prompt = _build_followup_prompt(
            _test_profile(),
            _test_opportunity(),
            None,
            _test_application(),
            followup_number=1,
            days_since=3,
        )
        assert "hiring team" in prompt.lower()
        assert "Acme Corp" in prompt

    def test_second_followup(self):
        prompt = _build_followup_prompt(
            _test_profile(),
            _test_opportunity(),
            _test_contact(),
            _test_application(),
            followup_number=2,
            days_since=10,
        )
        assert "FINAL follow-up" in prompt
        assert "second and final" in prompt

    def test_includes_skills(self):
        prompt = _build_followup_prompt(
            _test_profile(),
            _test_opportunity(),
            None,
            _test_application(),
            followup_number=1,
            days_since=5,
        )
        assert "Python" in prompt

    def test_includes_description_snippet(self):
        prompt = _build_followup_prompt(
            _test_profile(),
            _test_opportunity(),
            None,
            _test_application(),
            followup_number=1,
            days_since=5,
        )
        assert "FastAPI experience" in prompt


# ---------------------------------------------------------------------------
# Draft generation
# ---------------------------------------------------------------------------


class TestDraftContactFollowup:
    async def test_returns_followup_content(self):
        result = await draft_contact_followup(
            _test_profile(),
            _test_opportunity(),
            _test_application(),
            _test_contact(),
            _model_override=TestModel(),
        )
        assert isinstance(result, FollowUpContent)

    async def test_has_all_fields(self):
        result = await draft_contact_followup(
            _test_profile(),
            _test_opportunity(),
            _test_application(),
            None,
            _model_override=TestModel(),
        )
        assert result.subject is not None
        assert result.body is not None
        assert result.channel_suggestion is not None
        assert result.tone_note is not None

    async def test_with_second_followup(self):
        result = await draft_contact_followup(
            _test_profile(),
            _test_opportunity(),
            _test_application(),
            _test_contact(),
            followup_number=2,
            days_since=14,
            _model_override=TestModel(),
        )
        assert isinstance(result, FollowUpContent)
