"""Tests for emplaiyed.scoring.scorer — batch opportunity scoring."""

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
    _build_batch_prompt,
    _format_opp_block,
    _format_profile_block,
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


class TestBuildBatchPrompt:
    def test_includes_profile_data(self):
        prompt = _build_batch_prompt(_test_profile(), [_test_opportunity()])
        assert "Test User" in prompt
        assert "Python" in prompt
        assert "Software Engineer" in prompt
        assert "Montreal" in prompt

    def test_includes_all_opportunities(self):
        opps = [
            _test_opportunity(company="CompanyA", title="Role A"),
            _test_opportunity(company="CompanyB", title="Role B"),
            _test_opportunity(company="CompanyC", title="Role C"),
        ]
        prompt = _build_batch_prompt(_test_profile(), opps)
        assert "[0]" in prompt
        assert "[1]" in prompt
        assert "[2]" in prompt
        assert "CompanyA" in prompt
        assert "CompanyB" in prompt
        assert "CompanyC" in prompt

    def test_truncates_descriptions(self):
        opp = _test_opportunity(description="x" * 3000)
        prompt = _build_batch_prompt(_test_profile(), [opp])
        # Description truncated to 500 chars per opp in batch mode
        assert "x" * 501 not in prompt

    def test_relative_scoring_instruction(self):
        prompt = _build_batch_prompt(_test_profile(), [_test_opportunity()])
        assert "RELATIVE" in prompt

    def test_includes_excluded_industries_none_by_default(self):
        prompt = _build_batch_prompt(_test_profile(), [_test_opportunity()])
        assert "Excluded industries: None" in prompt

    def test_includes_excluded_industries_when_set(self):
        profile = _test_profile()
        profile.aspirations.excluded_industries = ["banking", "insurance"]
        prompt = _build_batch_prompt(profile, [_test_opportunity()])
        assert "banking" in prompt
        assert "insurance" in prompt
        assert "score it **0**" in prompt.lower() or "score it **0**" in prompt


class TestFormatHelpers:
    def test_format_profile_block(self):
        fields = _format_profile_block(_test_profile())
        assert fields["name"] == "Test User"
        assert "Python" in fields["skills"]
        assert "Montreal" in fields["location_prefs"]

    def test_format_opp_block(self):
        block = _format_opp_block(0, _test_opportunity())
        assert "[0]" in block
        assert "Acme Corp" in block
        assert "Software Developer" in block


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

    async def test_creates_applications_when_db_provided(
        self, tmp_path: Path, monkeypatch
    ):
        from emplaiyed.core.database import save_opportunity

        # TestModel produces score=0; set threshold to 0 so all land in SCORED.
        monkeypatch.setattr("emplaiyed.llm.config.SCORE_THRESHOLD", 0)

        db_conn = init_db(tmp_path / "test.db")
        opps = [
            _test_opportunity(company="Company A"),
            _test_opportunity(company="Company B"),
        ]
        for opp in opps:
            save_opportunity(db_conn, opp)

        results = await score_opportunities(
            _test_profile(), opps, db_conn=db_conn, _model_override=TestModel()
        )
        apps = list_applications(db_conn)
        assert len(apps) == 2
        assert all(a.status == ApplicationStatus.SCORED for a in apps)
        db_conn.close()

    async def test_persists_scoring_fields_in_applications(self, tmp_path: Path):
        from emplaiyed.core.database import save_opportunity

        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity(company="ScoredCo")
        save_opportunity(db_conn, opp)

        results = await score_opportunities(
            _test_profile(), [opp], db_conn=db_conn, _model_override=TestModel()
        )
        apps = list_applications(db_conn)
        assert len(apps) == 1
        app = apps[0]
        assert app.score is not None
        assert app.justification is not None
        assert app.day_to_day is not None
        assert app.why_it_fits is not None
        db_conn.close()

    async def test_below_threshold_apps_get_below_threshold_status(
        self, tmp_path: Path, monkeypatch
    ):
        """Apps scoring below SCORE_THRESHOLD get BELOW_THRESHOLD status."""
        from emplaiyed.core.database import save_opportunity

        # TestModel produces score=0; threshold=30 means all are below.
        monkeypatch.setattr("emplaiyed.llm.config.SCORE_THRESHOLD", 30)

        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity(company="LowScoreCo")
        save_opportunity(db_conn, opp)

        await score_opportunities(
            _test_profile(), [opp], db_conn=db_conn, _model_override=TestModel()
        )
        apps = list_applications(db_conn)
        assert len(apps) == 1
        assert apps[0].status == ApplicationStatus.BELOW_THRESHOLD
        db_conn.close()

    async def test_no_applications_without_db(self):
        opps = [_test_opportunity()]
        results = await score_opportunities(
            _test_profile(), opps, _model_override=TestModel()
        )
        assert len(results) == 1

    async def test_empty_list_returns_empty(self):
        results = await score_opportunities(
            _test_profile(), [], _model_override=TestModel()
        )
        assert results == []
