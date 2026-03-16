"""Tests for emplaiyed.inbox.classifier."""

from __future__ import annotations

import json

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart

from emplaiyed.inbox.classifier import (
    ACTIONABLE_CATEGORIES,
    EmailCategory,
    EmailClassification,
    classify_email,
)


def _make_classifier_model(category: str, action: bool = True, urgency: str = "medium"):
    """Return a FunctionModel that produces a fixed classification."""
    payload = {
        "category": category,
        "requires_action": action,
        "urgency": urgency,
        "summary": f"Test summary for {category}",
        "suggested_next_step": "Reply to the email" if action else None,
    }

    async def _handler(messages, info):
        return ModelResponse(parts=[TextPart(content=json.dumps(payload))])

    return FunctionModel(_handler)


class TestEmailClassification:
    def test_category_values(self):
        assert EmailCategory.INTERVIEW_INVITE == "INTERVIEW_INVITE"
        assert EmailCategory.IRRELEVANT == "IRRELEVANT"

    def test_actionable_categories_subset(self):
        assert EmailCategory.INTERVIEW_INVITE in ACTIONABLE_CATEGORIES
        assert EmailCategory.OFFER in ACTIONABLE_CATEGORIES
        assert EmailCategory.IRRELEVANT not in ACTIONABLE_CATEGORIES
        assert EmailCategory.REJECTION not in ACTIONABLE_CATEGORIES

    def test_classification_model(self):
        c = EmailClassification(
            category=EmailCategory.INTERVIEW_INVITE,
            requires_action=True,
            urgency="high",
            summary="Interview invite from Acme",
            suggested_next_step="Reply to schedule",
        )
        assert c.requires_action is True
        assert c.urgency == "high"


class TestClassifyEmail:
    async def test_classify_interview_invite(self):
        model = _make_classifier_model("INTERVIEW_INVITE", action=True, urgency="high")
        result = await classify_email(
            subject="Interview Invitation - Backend Developer",
            from_address="hr@acme.com",
            from_name="Acme HR",
            body_text="We'd like to schedule an interview...",
            _model_override=model,
        )
        assert result.category == EmailCategory.INTERVIEW_INVITE
        assert result.requires_action is True
        assert result.urgency == "high"

    async def test_classify_rejection(self):
        model = _make_classifier_model("REJECTION", action=False, urgency="low")
        result = await classify_email(
            subject="Thank you for your application",
            from_address="noreply@corp.com",
            from_name="Corp",
            body_text="We regret to inform you...",
            _model_override=model,
        )
        assert result.category == EmailCategory.REJECTION
        assert result.requires_action is False

    async def test_classify_irrelevant(self):
        model = _make_classifier_model("IRRELEVANT", action=False, urgency="low")
        result = await classify_email(
            subject="Your weekly newsletter",
            from_address="news@spam.com",
            from_name="Spam Inc",
            body_text="Buy our stuff!",
            _model_override=model,
        )
        assert result.category == EmailCategory.IRRELEVANT

    async def test_body_truncation(self):
        """Very long bodies should not crash — they are truncated in the prompt."""
        model = _make_classifier_model("IRRELEVANT", action=False, urgency="low")
        result = await classify_email(
            subject="Test",
            from_address="test@test.com",
            from_name="Test",
            body_text="x" * 10000,
            _model_override=model,
        )
        assert result.category == EmailCategory.IRRELEVANT
