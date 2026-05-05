"""Tests for the Browser Use task prompt builder."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from emplaiyed.apply.prompt_builder import build_apply_task_prompt, build_candidate_json
from emplaiyed.core.models import Address, Opportunity, Profile


@pytest.fixture
def profile():
    return Profile(
        name="Jean Dupont",
        email="moi@jpelletier.org",
        phone="+1-514-555-1234",
        linkedin="https://linkedin.com/in/jean",
        github="https://github.com/jean",
        address=Address(city="Montreal", province_state="QC", country="Canada"),
    )


@pytest.fixture
def opportunity():
    return Opportunity(
        id="opp-1",
        short_id="abc123",
        source="indeed",
        source_url="https://example.com/job/1",
        company="TestCo",
        title="Engineer",
        description="Build stuff",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


class TestBuildCandidateJson:
    def test_contains_candidate_fields(self, profile, opportunity):
        result = build_candidate_json(profile, opportunity)
        data = json.loads(result)
        assert data["candidate"]["name"] == "Jean Dupont"
        assert data["candidate"]["email"] == "moi@jpelletier.org"
        assert data["candidate"]["phone"] == "+1-514-555-1234"
        assert data["candidate"]["city"] == "Montreal"
        assert data["candidate"]["linkedin"] == "https://linkedin.com/in/jean"

    def test_contains_job_fields(self, profile, opportunity):
        result = build_candidate_json(profile, opportunity)
        data = json.loads(result)
        assert data["job"]["company"] == "TestCo"
        assert data["job"]["title"] == "Engineer"
        assert data["job"]["url"] == "https://example.com/job/1"

    def test_handles_no_address(self, opportunity):
        profile = Profile(name="Test", email="test@example.com")
        result = build_candidate_json(profile, opportunity)
        data = json.loads(result)
        assert data["candidate"]["city"] is None


class TestBuildApplyTaskPrompt:
    def test_contains_candidate_info(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert "Jean Dupont" in prompt
        assert "moi@jpelletier.org" in prompt
        assert "TestCo" in prompt

    def test_contains_account_email(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert "moi+abc123@jpelletier.org" in prompt

    def test_contains_pdf_references(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert "resume.pdf" in prompt
        assert "cover_letter.pdf" in prompt

    def test_skip_optional_instruction(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert "SKIP all optional fields" in prompt

    def test_no_fabrication_instruction(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert "Do NOT fabricate" in prompt

    def test_email_verification_instruction(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert "needs_email_verification" in prompt

    def test_na_instruction_for_missing_required_fields(self, profile, opportunity):
        prompt = build_apply_task_prompt(
            profile, opportunity, account_email="moi+abc123@jpelletier.org"
        )
        assert '"N/A"' in prompt
        assert "LinkedIn" in prompt
        assert "do not stop or report a blocker" in prompt.lower()
