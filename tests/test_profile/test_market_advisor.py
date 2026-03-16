"""Tests for emplaiyed.profile.market_advisor — market gap analysis."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.database import init_db, save_application, save_opportunity
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Aspirations,
    Certification,
    Employment,
    Opportunity,
    Profile,
)
from emplaiyed.profile.market_advisor import (
    MarketGapReport,
    _build_advisor_prompt,
    analyze_market_gaps,
)


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Alice Smith",
        email="alice@example.com",
        skills=["Python", "AWS", "Docker"],
        employment_history=[
            Employment(
                company="Acme",
                title="Senior Engineer",
                highlights=["Led migration to AWS", "Built CI/CD pipeline"],
            ),
        ],
        certifications=[Certification(name="AWS SAA", issuer="Amazon")],
        aspirations=Aspirations(
            target_roles=["Staff Engineer", "Cloud Architect"],
            salary_target=150000,
        ),
    )


@pytest.fixture
def opportunities() -> list[Opportunity]:
    now = datetime.now()
    return [
        Opportunity(
            id=f"opp-{i}",
            source="jobbank",
            company=f"Company{i}",
            title="Cloud Engineer",
            description=f"Looking for a cloud engineer with Kubernetes and Terraform experience. Job {i}.",
            scraped_at=now,
        )
        for i in range(5)
    ]


@pytest.fixture
def db(tmp_path: Path):
    conn = init_db(tmp_path / "advisor.db")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Prompt building tests
# ---------------------------------------------------------------------------


class TestBuildAdvisorPrompt:
    def test_contains_candidate_name(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Alice Smith" in prompt

    def test_contains_skills(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Python" in prompt
        assert "AWS" in prompt

    def test_contains_employment(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Acme" in prompt
        assert "Senior Engineer" in prompt

    def test_contains_highlights(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Led migration to AWS" in prompt

    def test_contains_certifications(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "AWS SAA" in prompt

    def test_contains_target_roles(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Staff Engineer" in prompt

    def test_contains_salary_target(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "$150,000" in prompt

    def test_contains_opportunities(self, profile, opportunities):
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Company0" in prompt
        assert "Kubernetes" in prompt

    def test_caps_at_30_opportunities(self, profile):
        now = datetime.now()
        many_opps = [
            Opportunity(
                id=f"opp-{i}",
                source="test",
                company=f"Co{i}",
                title="Role",
                description="desc",
                scraped_at=now,
            )
            for i in range(50)
        ]
        prompt = _build_advisor_prompt(profile, many_opps)
        assert "Co29" in prompt
        assert "Co30" not in prompt  # 0-indexed, so 30th is index 30

    def test_minimal_profile(self, opportunities):
        """Works with a profile that has only name/email."""
        profile = Profile(name="Bob", email="bob@example.com")
        prompt = _build_advisor_prompt(profile, opportunities)
        assert "Bob" in prompt
        assert "Company0" in prompt


# ---------------------------------------------------------------------------
# analyze_market_gaps integration tests
# ---------------------------------------------------------------------------


class TestAnalyzeMarketGaps:
    async def test_no_apps_returns_empty_report(self, profile, db):
        """When no scored applications exist, return a summary-only report."""
        report = await analyze_market_gaps(profile, db, _model_override=TestModel())
        assert isinstance(report, MarketGapReport)
        assert "No scored opportunities" in report.summary

    async def test_with_scored_apps(self, profile, opportunities, db):
        """With scored apps, the LLM is called and returns a MarketGapReport."""
        now = datetime.now()
        for opp in opportunities:
            save_opportunity(db, opp)
            app = Application(
                id=f"app-{opp.id}",
                opportunity_id=opp.id,
                status=ApplicationStatus.SCORED,
                score=85.0,
                created_at=now,
                updated_at=now,
            )
            save_application(db, app)

        report = await analyze_market_gaps(profile, db, _model_override=TestModel())
        assert isinstance(report, MarketGapReport)
        # TestModel returns default values — summary should be a string
        assert isinstance(report.summary, str)

    async def test_sorts_by_score(self, profile, db):
        """Higher-scored applications should be preferred."""
        now = datetime.now()
        for i, score in enumerate([50.0, 90.0, 70.0]):
            opp = Opportunity(
                id=f"opp-{i}",
                source="test",
                company=f"Co{i}",
                title="Role",
                description=f"Job description {i}",
                scraped_at=now,
            )
            save_opportunity(db, opp)
            app = Application(
                id=f"app-{i}",
                opportunity_id=f"opp-{i}",
                status=ApplicationStatus.SCORED,
                score=score,
                created_at=now,
                updated_at=now,
            )
            save_application(db, app)

        # Should not raise — the function sorts and processes them
        report = await analyze_market_gaps(profile, db, _model_override=TestModel())
        assert isinstance(report, MarketGapReport)


# ---------------------------------------------------------------------------
# MarketGapReport model tests
# ---------------------------------------------------------------------------


class TestMarketGapReport:
    def test_defaults(self):
        """All list fields default to empty."""
        report = MarketGapReport(summary="Test summary")
        assert report.skill_gaps == []
        assert report.experience_gaps == []
        assert report.project_suggestions == []
        assert report.certification_suggestions == []
        assert report.profile_wording == []
        assert report.strengths == []
