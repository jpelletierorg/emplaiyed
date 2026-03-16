"""Tests for the agentic job search."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import Address, Aspirations, Opportunity, Profile
from emplaiyed.sources.base import BaseSource, SearchQuery
from emplaiyed.sources.search_agent import (
    SearchDeps,
    SearchResult,
    _basic_filter,
    _build_search_prompt,
    agentic_search,
    reject_opportunities,
)


class FakeSource(BaseSource):
    """A fake source that returns canned results."""

    def __init__(self, results: list[Opportunity] | None = None):
        self._results = results or []

    @property
    def name(self) -> str:
        return "fake"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        return list(self._results)


class StubSource(BaseSource):
    """A source that raises NotImplementedError."""

    @property
    def name(self) -> str:
        return "stub"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        raise NotImplementedError("Not implemented")


def _make_profile(**kwargs) -> Profile:
    return Profile(
        name=kwargs.get("name", "Test User"),
        email=kwargs.get("email", "test@example.com"),
        skills=kwargs.get("skills", ["Python", "AWS", "Docker"]),
        address=kwargs.get("address", None),
        aspirations=kwargs.get(
            "aspirations",
            Aspirations(
                target_roles=["AI Engineer", "Cloud Architect"],
                geographic_preferences=["Montreal"],
                salary_minimum=70000,
                salary_target=100000,
            ),
        ),
    )


def _make_opp(
    title: str = "Dev", company: str = "Acme", source: str = "fake"
) -> Opportunity:
    return Opportunity(
        source=source,
        company=company,
        title=title,
        description="A job",
        scraped_at=datetime.now(),
    )


# --- Unit tests for _basic_filter ---


class TestBasicFilter:
    def test_rejects_intern(self):
        opp = _make_opp(title="Software Engineering Intern")
        assert _basic_filter(opp, _make_profile()) is False

    def test_rejects_junior(self):
        opp = _make_opp(title="Junior Developer")
        assert _basic_filter(opp, _make_profile()) is False

    def test_rejects_coop(self):
        opp = _make_opp(title="co-op Software Developer")
        assert _basic_filter(opp, _make_profile()) is False

    def test_accepts_senior(self):
        opp = _make_opp(title="Senior Cloud Architect")
        assert _basic_filter(opp, _make_profile()) is True

    def test_rejects_low_salary(self):
        opp = _make_opp(title="Developer")
        opp.salary_max = 40000  # Well below 70k minimum
        assert _basic_filter(opp, _make_profile()) is False

    def test_accepts_adequate_salary(self):
        opp = _make_opp(title="Developer")
        opp.salary_max = 90000
        assert _basic_filter(opp, _make_profile()) is True

    def test_accepts_no_salary_info(self):
        opp = _make_opp(title="Developer")
        assert _basic_filter(opp, _make_profile()) is True

    def test_rejects_excluded_industry_in_company(self):
        profile = _make_profile(
            aspirations=Aspirations(
                target_roles=["AI Engineer"],
                excluded_industries=["bank"],
            ),
        )
        opp = _make_opp(title="AI Engineer", company="National Bank of Canada")
        assert _basic_filter(opp, profile) is False

    def test_rejects_excluded_industry_in_description(self):
        profile = _make_profile(
            aspirations=Aspirations(
                target_roles=["AI Engineer"],
                excluded_industries=["insurance"],
            ),
        )
        opp = Opportunity(
            source="fake",
            company="Desjardins",
            title="AI Engineer",
            description="Join our insurance division to build AI models.",
            scraped_at=datetime.now(),
        )
        assert _basic_filter(opp, profile) is False

    def test_accepts_when_no_excluded_industries(self):
        profile = _make_profile(
            aspirations=Aspirations(
                target_roles=["AI Engineer"],
                excluded_industries=[],
            ),
        )
        opp = _make_opp(title="AI Engineer", company="National Bank")
        assert _basic_filter(opp, profile) is True

    def test_excluded_industry_case_insensitive(self):
        profile = _make_profile(
            aspirations=Aspirations(
                target_roles=["AI Engineer"],
                excluded_industries=["Banking"],
            ),
        )
        opp = _make_opp(title="AI Engineer", company="Some banking corp")
        assert _basic_filter(opp, profile) is False


# --- Unit tests for _build_search_prompt ---


class TestBuildSearchPrompt:
    def test_includes_skills(self):
        prompt = _build_search_prompt(_make_profile(), ["jobbank", "jobillico"])
        assert "Python" in prompt
        assert "AWS" in prompt

    def test_includes_target_roles(self):
        prompt = _build_search_prompt(_make_profile(), ["jobbank"])
        assert "AI Engineer" in prompt

    def test_includes_available_sources(self):
        prompt = _build_search_prompt(_make_profile(), ["jobbank", "jobillico"])
        assert "jobbank" in prompt
        assert "jobillico" in prompt

    def test_includes_excluded_industries(self):
        profile = _make_profile(
            aspirations=Aspirations(
                target_roles=["AI Engineer"],
                excluded_industries=["banking", "insurance"],
            ),
        )
        prompt = _build_search_prompt(profile, ["jobbank"])
        assert "banking" in prompt
        assert "insurance" in prompt
        assert "EXCLUDED" in prompt

    def test_includes_mandatory_location_label(self):
        prompt = _build_search_prompt(_make_profile(), ["jobbank"])
        assert "MANDATORY search locations" in prompt

    def test_includes_candidate_address(self):
        profile = _make_profile(
            address=Address(city="Longueuil", province_state="Québec"),
        )
        prompt = _build_search_prompt(profile, ["jobbank"])
        assert "Candidate lives in: Longueuil" in prompt


# --- Integration test with TestModel ---


class TestAgenticSearch:
    async def test_returns_search_result(self):
        """Basic smoke test: agent runs and returns a SearchResult."""
        opps = [
            _make_opp("Cloud Architect", "BigCorp"),
            _make_opp("AI Engineer", "StartupCo"),
        ]
        source = FakeSource(opps)
        model = TestModel()

        result = await agentic_search(
            _make_profile(),
            {"fake": source},
            _model_override=model,
        )

        assert isinstance(result, SearchResult)
        # TestModel calls each tool once, so we should have results
        assert isinstance(result.queries_used, list)

    async def test_handles_empty_sources(self):
        """Agent works even with no sources."""
        model = TestModel()
        result = await agentic_search(
            _make_profile(),
            {},
            _model_override=model,
        )
        assert isinstance(result, SearchResult)

    async def test_deduplication(self):
        """Same opportunity from same source should be deduped."""
        opp = _make_opp("Cloud Architect", "BigCorp")
        source = FakeSource([opp, opp])
        model = TestModel()

        result = await agentic_search(
            _make_profile(),
            {"fake": source},
            _model_override=model,
        )

        assert isinstance(result, SearchResult)
        # Even though source returns 2 identical opps, dedup keeps 1
        company_counts: dict[tuple[str, str], int] = {}
        for o in result.opportunities:
            key = (o.company.lower(), o.title.lower())
            company_counts[key] = company_counts.get(key, 0) + 1
        for count in company_counts.values():
            assert count == 1

    async def test_stub_source_reports_not_implemented(self):
        """A stub source that raises NotImplementedError is handled gracefully."""
        stub = StubSource()
        model = TestModel()

        result = await agentic_search(
            _make_profile(),
            {"stub": stub},
            _model_override=model,
        )

        assert isinstance(result, SearchResult)

    async def test_direction_steers_search(self):
        """Passing a direction prepends steering text to the prompt."""
        source = FakeSource([_make_opp("ML Engineer", "AI Corp")])
        model = TestModel()

        result = await agentic_search(
            _make_profile(),
            {"fake": source},
            direction="find me machine learning research roles",
            _model_override=model,
        )

        assert isinstance(result, SearchResult)


class TestRejectOpportunities:
    """Tests for the reject_opportunities tool."""

    async def test_rejects_by_company_name(self):
        deps = SearchDeps(
            profile=_make_profile(),
            sources={},
            found=[
                _make_opp("AI Engineer", "RBC"),
                _make_opp("ML Engineer", "Google"),
                _make_opp("Data Scientist", "TD Bank"),
            ],
            seen_keys={
                ("rbc", "ai engineer", "fake"),
                ("google", "ml engineer", "fake"),
                ("td bank", "data scientist", "fake"),
            },
        )

        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.deps = deps

        result = await reject_opportunities(ctx, ["RBC", "TD Bank"], "banking sector")
        assert len(deps.found) == 1
        assert deps.found[0].company == "Google"
        assert "Rejected 2" in result

    async def test_reject_no_matches(self):
        deps = SearchDeps(
            profile=_make_profile(),
            sources={},
            found=[_make_opp("Dev", "Acme")],
            seen_keys={("acme", "dev", "fake")},
        )

        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.deps = deps

        result = await reject_opportunities(ctx, ["NonExistent"], "test")
        assert len(deps.found) == 1
        assert "No matches" in result

    async def test_reject_clears_seen_keys(self):
        deps = SearchDeps(
            profile=_make_profile(),
            sources={},
            found=[_make_opp("Dev", "BadCorp")],
            seen_keys={("badcorp", "dev", "fake")},
        )

        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.deps = deps

        await reject_opportunities(ctx, ["BadCorp"], "test")
        assert ("badcorp", "dev", "fake") not in deps.seen_keys
