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
    CVCertification,
    CVEducation,
    GeneratedCV,
    CVExperience,
    SkillCategory,
    _build_cv_prompt,
    generate_cv,
)


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Alice Test",
        email="alice@example.com",
        phone="+1-555-0000",
        linkedin="https://linkedin.com/in/alicetest",
        github="https://github.com/alicetest",
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
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "Alice Test" in prompt

    def test_includes_skills(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "Python" in prompt
        assert "AWS" in prompt

    def test_includes_opportunity_company(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "BigCorp" in prompt

    def test_includes_employment(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "Acme" in prompt
        assert "Senior Dev" in prompt

    def test_includes_linkedin_and_github(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "linkedin.com/in/alicetest" in prompt
        assert "github.com/alicetest" in prompt

    def test_includes_car_format_instruction(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "CAR-format" in prompt

    def test_highlights_passed_verbatim(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "English")
        assert "Shipped v2" in prompt
        assert "raw material" in prompt

    def test_prompt_includes_explicit_language(self, profile, opportunity):
        prompt = _build_cv_prompt(profile, opportunity, "French")
        assert "French" in prompt
        assert "detect" not in prompt.lower()


class TestGenerateCV:
    async def test_returns_generated_cv(self, profile, opportunity):
        model = TestModel()
        result = await generate_cv(profile, opportunity, language="English", _model_override=model)
        assert isinstance(result, GeneratedCV)

    async def test_generated_cv_has_required_fields(self, profile, opportunity):
        model = TestModel()
        result = await generate_cv(profile, opportunity, language="English", _model_override=model)
        assert result.name
        assert result.email
        assert result.professional_title
        assert result.summary is not None


class TestGeneratedCVModel:
    def test_minimal(self):
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            summary="Experienced developer.",
            skill_categories=[SkillCategory(category="Languages", skills=["Python"])],
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
            summary="Experienced developer.",
            skill_categories=[SkillCategory(category="Languages", skills=["Python"])],
            experience=[exp],
            education=[CVEducation(institution="Laval", degree="BSc", field="CS")],
        )
        assert len(cv.experience) == 1
        assert cv.experience[0].highlights == ["Built things"]

    def test_structured_education(self):
        edu = CVEducation(
            institution="MIT",
            degree="MSc",
            field="Computer Science",
            start_date="2018",
            end_date="2020",
        )
        assert edu.institution == "MIT"
        assert edu.end_date == "2020"

    def test_structured_certification(self):
        cert = CVCertification(
            name="AWS SAA",
            issuer="Amazon",
            date="2023",
        )
        assert cert.name == "AWS SAA"
        assert cert.issuer == "Amazon"

    def test_skill_categories(self):
        cat = SkillCategory(category="Cloud", skills=["AWS", "GCP"])
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            summary="Cloud expert.",
            skill_categories=[cat],
            experience=[],
            education=[],
        )
        assert len(cv.skill_categories) == 1
        assert cv.skill_categories[0].category == "Cloud"
        assert "AWS" in cv.skill_categories[0].skills
