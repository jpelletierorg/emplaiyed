"""Tests for emplaiyed.scoring.scorer — opportunity scoring."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.database import init_db, list_applications
from emplaiyed.core.models import (
    ApplicationStatus,
    Aspirations,
    Opportunity,
    Profile,
    ScoredOpportunity,
)
from emplaiyed.scoring.scorer import (
    _build_score_prompt,
    score_opportunities,
    score_opportunity,
)


def _test_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python", "AWS", "Docker", "Kubernetes", "SQL"],
        aspirations=Aspirations(
            target_roles=["Software Engineer"],
            salary_minimum=80000,
            salary_target=120000,
            geographic_preferences=["Montreal"],
        ),
    )


def _test_opportunity(**overrides) -> Opportunity:
    defaults = dict(
        source="jobbank",
        company="Acme Corp",
        title="Software Developer",
        description="We need a Python developer with AWS experience.",
        location="Montreal, QC",
        salary_min=90000,
        salary_max=110000,
        scraped_at=datetime.now(),
    )
    defaults.update(overrides)
    return Opportunity(**defaults)


class TestBuildScorePrompt:
    def test_includes_profile_data(self):
        prompt = _build_score_prompt(_test_profile(), _test_opportunity())
        assert "Test User" in prompt
        assert "Python" in prompt
        assert "Software Engineer" in prompt
        assert "Montreal" in prompt

    def test_includes_opportunity_data(self):
        prompt = _build_score_prompt(_test_profile(), _test_opportunity())
        assert "Acme Corp" in prompt
        assert "Software Developer" in prompt
        assert "Python developer" in prompt

    def test_truncates_long_descriptions(self):
        opp = _test_opportunity(description="x" * 3000)
        prompt = _build_score_prompt(_test_profile(), opp)
        # Should be truncated to 1500 chars
        assert len(prompt) < 3000 + 500  # prompt template + truncated desc


class TestScoreOpportunity:
    async def test_returns_scored_opportunity(self):
        result = await score_opportunity(
            _test_profile(),
            _test_opportunity(),
            _model_override=TestModel(),
        )
        assert isinstance(result, ScoredOpportunity)
        assert 0 <= result.score <= 100
        assert result.opportunity.company == "Acme Corp"

    async def test_justification_is_not_empty(self):
        result = await score_opportunity(
            _test_profile(),
            _test_opportunity(),
            _model_override=TestModel(),
        )
        assert result.justification  # not empty


class TestScoreOpportunities:
    async def test_scores_multiple(self):
        opps = [
            _test_opportunity(company="Company A"),
            _test_opportunity(company="Company B"),
        ]
        results = await score_opportunities(
            _test_profile(), opps, _model_override=TestModel()
        )
        assert len(results) == 2
        assert all(isinstance(r, ScoredOpportunity) for r in results)

    async def test_sorted_by_score_descending(self):
        opps = [_test_opportunity() for _ in range(3)]
        results = await score_opportunities(
            _test_profile(), opps, _model_override=TestModel()
        )
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_creates_applications_when_db_provided(self, tmp_path: Path):
        from emplaiyed.core.database import save_opportunity

        db_conn = init_db(tmp_path / "test.db")
        opps = [
            _test_opportunity(company="Company A"),
            _test_opportunity(company="Company B"),
        ]
        # Save opportunities first (FK constraint)
        for opp in opps:
            save_opportunity(db_conn, opp)

        results = await score_opportunities(
            _test_profile(), opps, db_conn=db_conn, _model_override=TestModel()
        )
        apps = list_applications(db_conn)
        assert len(apps) == 2
        assert all(a.status == ApplicationStatus.SCORED for a in apps)
        db_conn.close()

    async def test_no_applications_without_db(self):
        opps = [_test_opportunity()]
        results = await score_opportunities(
            _test_profile(), opps, _model_override=TestModel()
        )
        assert len(results) == 1
        # No DB means no applications created — just verify no crash
