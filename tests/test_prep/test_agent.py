"""Tests for emplaiyed.prep.agent — interview prep generation."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import (
    Aspirations,
    Employment,
    Opportunity,
    Profile,
)
from emplaiyed.prep.agent import PrepSheet, generate_prep


def _test_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python", "AWS", "Docker"],
        employment_history=[
            Employment(company="Big Corp", title="Lead Architect", start_date=None)
        ],
        aspirations=Aspirations(
            salary_minimum=80000,
            salary_target=120000,
        ),
    )


def _test_opportunity() -> Opportunity:
    return Opportunity(
        source="jobbank",
        company="Interview Co",
        title="Senior Developer",
        description="Looking for experienced developers.",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


class TestGeneratePrep:
    async def test_returns_prep_sheet(self):
        result = await generate_prep(
            _test_profile(),
            _test_opportunity(),
            _model_override=TestModel(),
        )
        assert isinstance(result, PrepSheet)
        assert result.company_summary  # not empty
        assert result.salary_notes  # not empty
