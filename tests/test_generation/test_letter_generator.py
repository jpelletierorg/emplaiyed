"""Tests for letter generation with TestModel."""

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
from emplaiyed.generation.letter_generator import (
    GeneratedLetter,
    _build_letter_prompt,
    generate_letter,
)


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Alice Test",
        email="alice@example.com",
        skills=["Python", "AWS", "Docker"],
        employment_history=[
            Employment(company="Acme", title="Senior Dev"),
        ],
        aspirations=Aspirations(
            target_roles=["Cloud Architect"],
            statement="I want to build cloud infrastructure at scale.",
        ),
    )


@pytest.fixture
def opportunity() -> Opportunity:
    return Opportunity(
        source="jobbank",
        company="BigCorp",
        title="Cloud Architect",
        description="Design cloud infrastructure.",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


class TestBuildLetterPrompt:
    def test_includes_candidate_name(self, profile, opportunity):
        prompt = _build_letter_prompt(profile, opportunity)
        assert "Alice Test" in prompt

    def test_includes_company(self, profile, opportunity):
        prompt = _build_letter_prompt(profile, opportunity)
        assert "BigCorp" in prompt

    def test_includes_career_statement(self, profile, opportunity):
        prompt = _build_letter_prompt(profile, opportunity)
        assert "cloud infrastructure at scale" in prompt

    def test_includes_recent_role(self, profile, opportunity):
        prompt = _build_letter_prompt(profile, opportunity)
        assert "Senior Dev" in prompt
        assert "Acme" in prompt


class TestGenerateLetter:
    async def test_returns_generated_letter(self, profile, opportunity):
        model = TestModel()
        result = await generate_letter(profile, opportunity, _model_override=model)
        assert isinstance(result, GeneratedLetter)

    async def test_generated_letter_has_required_fields(self, profile, opportunity):
        model = TestModel()
        result = await generate_letter(profile, opportunity, _model_override=model)
        assert result.greeting
        assert result.body
        assert result.closing
        assert result.signature_name


class TestGeneratedLetterModel:
    def test_creation(self):
        letter = GeneratedLetter(
            greeting="Dear Hiring Manager,",
            body="I am writing to express my interest...",
            closing="Sincerely,",
            signature_name="Alice Test",
        )
        assert letter.greeting.startswith("Dear")
        assert letter.signature_name == "Alice Test"
