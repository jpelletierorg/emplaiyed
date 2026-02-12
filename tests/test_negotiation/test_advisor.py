"""Tests for emplaiyed.negotiation.advisor — negotiation strategy generation."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import (
    Aspirations,
    Offer,
    OfferStatus,
    Opportunity,
    Profile,
)
from emplaiyed.negotiation.advisor import NegotiationStrategy, generate_negotiation


def _test_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python"],
        aspirations=Aspirations(
            salary_minimum=80000,
            salary_target=120000,
        ),
    )


def _test_opportunity() -> Opportunity:
    return Opportunity(
        source="jobbank",
        company="Offer Corp",
        title="Developer",
        description="A job.",
        scraped_at=datetime.now(),
    )


def _test_offer(application_id: str = "test-app") -> Offer:
    return Offer(
        application_id=application_id,
        salary=100000,
        status=OfferStatus.PENDING,
        created_at=datetime.now(),
    )


class TestGenerateNegotiation:
    async def test_returns_strategy(self):
        result = await generate_negotiation(
            _test_profile(),
            _test_opportunity(),
            _test_offer(),
            _model_override=TestModel(),
        )
        assert isinstance(result, NegotiationStrategy)
        assert result.analysis
        assert result.recommended_counter >= 0  # TestModel returns 0
        assert result.counter_email_subject
        assert result.counter_email_body
