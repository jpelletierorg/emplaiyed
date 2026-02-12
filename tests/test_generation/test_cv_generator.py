"""Tests for CV generation with TestModel."""

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
from emplaiyed.generation.cv_generator import (
    GeneratedCV,
    CVExperience,
    _build_cv_prompt,
    generate_cv,
)


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Alice Test",
        email="alice@example.com",
        phone="+1-555-0000",
        skills=["Python", "AWS", "Docker"],
        employment_history=[
            Employment(
                company="Acme",
                title="Senior Dev",
                description="Built cloud stuff",
                highlights=["Shipped v2"],
            ),
        ],
        aspirations=Aspirations(
            target_roles=["Cloud Architect"],
            work_arrangement=["remote"],
        ),
    )


@pytest.fixture
def opportunity() -> Opportunity:
    return Opportunity(
        source="jobbank",
        company="BigCorp",
        title="Cloud Architect",
        description="Design cloud infrastructure. AWS, Python, Docker required.",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


class TestBuildCvPrompt:
    def test_includes_candidate_name(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity)
        assert "Alice Test" in prompt

    def test_includes_skills(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity)
        assert "Python" in prompt
        assert "AWS" in prompt

    def test_includes_opportunity_company(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity)
        assert "BigCorp" in prompt

    def test_includes_employment(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity)
        assert "Acme" in prompt
        assert "Senior Dev" in prompt


class TestGenerateCV:
    async def test_returns_generated_cv(self, profile, opportunity):
        model = TestModel()
        result = await generate_cv(profile, opportunity, _model_override=model)
        assert isinstance(result, GeneratedCV)

    async def test_generated_cv_has_required_fields(self, profile, opportunity):
        model = TestModel()
        result = await generate_cv(profile, opportunity, _model_override=model)
        assert result.name
        assert result.email
        assert result.professional_title


class TestGeneratedCVModel:
    def test_minimal(self):
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            skills=["Python"],
            experience=[],
            education=[],
        )
        assert cv.certifications == []
        assert cv.languages == []

    def test_with_experience(self):
        exp = CVExperience(
            company="Acme",
            title="Dev",
            highlights=["Built things"],
        )
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            skills=["Python"],
            experience=[exp],
            education=["BSc CS, Laval"],
        )
        assert len(cv.experience) == 1
        assert cv.experience[0].highlights == ["Built things"]
