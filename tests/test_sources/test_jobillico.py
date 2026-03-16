"""Tests for emplaiyed.sources.jobillico — Jobillico Quebec job board scraper."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from emplaiyed.core.database import init_db, list_opportunities, save_application
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
from emplaiyed.sources.base import SearchQuery
from emplaiyed.sources.jobillico import (
    JobillicoSource,
    _build_search_url,
    _clean_job_url,
    _extract_job_id_from_href,
    _parse_days_ago,
    parse_search_results,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = """
<html>
<body>
<div id="jobOffersList">
  <article class="has-tag-partner card card--clickable none-trigger"
           onclick="document.getElementById('0').click();" ref="job0">
    <div class="card__content">
      <header class="relative">
        <h2 class="h3 mb0 word-break">
          <a href="/see-partner-offer/21989278?lshs=abc123&amp;ipg=1"
             id="0" rel="nofollow" target="_blank">
            SailPoint Developer
          </a>
        </h2>
        <h3 class="h4">
          <span class="link companyLink">Best Buy Canada</span>
        </h3>
      </header>
      <p class="xs word-break">
        Are you enthusiastic about empowering and influencing the Best Buy business?
      </p>
      <ul class="list list--has-no-bullets">
        <li class="list__item mb1">
          <span class="icon icon--information icon--information--position"></span>
          <p class="inline xs valign-middle">Vancouver - BC</p>
        </li>
        <li class="list__item">
          <span class="icon icon--information icon--information--calendar"></span>
          <p class="inline valign-middle">
            <time class="xs" datetime="2020-06-16">5 day(s)</time>
          </p>
        </li>
      </ul>
    </div>
  </article>

  <article class="no-tag-partner card card--clickable has-no-border-top has-tag-urgent"
           data-company-id="4357"
           data-job-url="national-bank/ai-chief-developer/16720230?lshs=abc123">
    <div class="card__content">
      <header class="relative">
        <h2 class="h3 mb0 pr5 word-break">
          <a class="is-unclickable-on-load"
             href="/en/job-offer/national-bank/ai-chief-developer/16720230?lshs=abc123&amp;ipg=1"
             id="1" rel="nofollow">
            AI Chief Developer
          </a>
        </h2>
        <h3 class="h4">
          <a class="link companyLink"
             href="/see-company/national-bank?lshs=abc123"
             target="_blank">
            National Bank
          </a>
        </h3>
      </header>
      <p class="xs word-break">
        A career as a Senior Developer in the Strategy, Data and Performance team.
      </p>
      <ul class="list list--has-no-bullets">
        <li class="list__item mb1">
          <span class="icon icon--information icon--information--position"></span>
          <p class="inline xs valign-middle">Montreal - QC</p>
        </li>
        <li class="list__item mb1">
          <span class="icon icon--information icon--information--clock"></span>
          <p class="inline xs valign-middle">Full time</p>
        </li>
        <li class="list__item">
          <span class="icon icon--information icon--information--calendar"></span>
          <p class="inline valign-middle">
            <time class="xs" datetime="2020-06-16">9 day(s)</time>
          </p>
        </li>
      </ul>
    </div>
  </article>

  <article class="no-tag-partner card card--clickable has-no-border-top no-tag-urgent"
           data-company-id="9999"
           data-job-url="brp-/power-bi-developer/16406122?lshs=abc123">
    <div class="card__content">
      <header class="relative">
        <h2 class="h3 mb0 pr5 word-break">
          <a class="is-unclickable-on-load"
             href="/en/job-offer/brp-/power-bi-developer/16406122?lshs=abc123&amp;ipg=1"
             id="2" rel="nofollow">
            Power BI Developer
          </a>
        </h2>
        <h3 class="h4">
          <a class="link companyLink"
             href="/see-company/brp-?lshs=abc123"
             target="_blank">
            BRP
          </a>
        </h3>
      </header>
      <p class="xs word-break">
        Join our team to build Power BI dashboards and analytics solutions.
      </p>
      <ul class="list list--has-no-bullets">
        <li class="list__item mb1">
          <span class="icon icon--information icon--information--position"></span>
          <p class="inline xs valign-middle">Sherbrooke - QC</p>
        </li>
        <li class="list__item mb1">
          <span class="icon icon--information icon--information--clock"></span>
          <p class="inline xs valign-middle">Full time</p>
        </li>
        <li class="list__item">
          <span class="icon icon--information icon--information--calendar"></span>
          <p class="inline valign-middle">
            <time class="xs" datetime="2020-06-16">30+ day(s)</time>
          </p>
        </li>
      </ul>
    </div>
  </article>
</div>
</body>
</html>
"""

SEARCH_RESULTS_EMPTY_HTML = """
<html>
<body>
<div id="jobOffersList">
</div>
</body>
</html>
"""

SEARCH_RESULTS_NO_CONTAINER_HTML = """
<html>
<body>
<div id="some-other-content">
  <p>No results here</p>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Mock HTTP helper
# ---------------------------------------------------------------------------


@contextmanager
def mock_jobillico_http(
    response_html: str,
) -> Generator[AsyncMock, None, None]:
    """Patch httpx.AsyncClient to return a canned HTML response.

    Yields the mock client so callers can inspect calls if needed.
    """
    response = httpx.Response(
        status_code=200,
        text=response_html,
        request=httpx.Request("GET", "https://www.jobillico.com/search-jobs"),
    )

    with patch("emplaiyed.sources.jobillico.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        yield mock_client


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestExtractJobId:
    @pytest.mark.parametrize(
        "href, expected",
        [
            ("/en/job-offer/national-bank/ai-chief-developer/16720230?lshs=abc", "16720230"),
            ("/see-partner-offer/21989278?lshs=abc", "p-21989278"),
        ],
        ids=["native_job_offer", "partner_offer"],
    )
    def test_extracts_id(self, href: str, expected: str) -> None:
        assert _extract_job_id_from_href(href) == expected

    @pytest.mark.parametrize(
        "href",
        ["/some/other/path", ""],
        ids=["no_match", "empty_string"],
    )
    def test_returns_none_for_invalid(self, href: str) -> None:
        assert _extract_job_id_from_href(href) is None


class TestCleanJobUrl:
    @pytest.mark.parametrize(
        "href, expected",
        [
            (
                "/en/job-offer/company/title/123?lshs=abc&ipg=1",
                "https://www.jobillico.com/en/job-offer/company/title/123",
            ),
            (
                "/see-partner-offer/456?tracking=true",
                "https://www.jobillico.com/see-partner-offer/456",
            ),
            (
                "https://www.jobillico.com/en/job-offer/co/title/789?x=1",
                "https://www.jobillico.com/en/job-offer/co/title/789",
            ),
        ],
        ids=["strips_query_params", "relative_url", "absolute_url"],
    )
    def test_clean_url(self, href: str, expected: str) -> None:
        assert _clean_job_url(href) == expected


class TestParseDaysAgo:
    @pytest.mark.parametrize(
        "text, expected_days_low, expected_days_high",
        [
            ("5 day(s)", 4, 6),
            ("30+ day(s)", 29, 31),
            ("1 day(s)", 0, 2),
        ],
        ids=["5_days", "30_plus_days", "1_day"],
    )
    def test_parses_day_strings(
        self, text: str, expected_days_low: int, expected_days_high: int
    ) -> None:
        result = _parse_days_ago(text)
        assert result is not None
        delta = datetime.now() - result
        days = delta.total_seconds() / 86400
        assert expected_days_low < days < expected_days_high

    @pytest.mark.parametrize(
        "text",
        ["Unknown", ""],
        ids=["no_match", "empty_string"],
    )
    def test_returns_none_for_unparseable(self, text: str) -> None:
        assert _parse_days_ago(text) is None


class TestBuildSearchUrl:
    @pytest.mark.parametrize(
        "query, url_must_contain, url_must_not_contain",
        [
            (
                SearchQuery(keywords=["python", "developer"]),
                ["jobillico.com/search-jobs", "skwd=python+developer"],
                [],
            ),
            (
                SearchQuery(keywords=["developer"], location="Montreal"),
                ["skwd=developer", "sjdpl=Montreal"],
                [],
            ),
            (
                SearchQuery(keywords=[]),
                ["jobillico.com/search-jobs"],
                ["skwd"],
            ),
            (
                SearchQuery(keywords=["data scientist"]),
                ["skwd=data+scientist"],
                ["sjdpl"],
            ),
        ],
        ids=["basic_keywords", "with_location", "no_keywords", "keywords_only"],
    )
    def test_build_url(
        self,
        query: SearchQuery,
        url_must_contain: list[str],
        url_must_not_contain: list[str],
    ) -> None:
        url = _build_search_url(query)
        for fragment in url_must_contain:
            assert fragment in url
        for fragment in url_must_not_contain:
            assert fragment not in url


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    def test_partner_listing(self) -> None:
        """Partner listing (index 0) — all fields."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        assert len(results) == 3

        partner = results[0]
        assert partner["job_id"] == "p-21989278"
        assert partner["title"] == "SailPoint Developer"
        assert partner["company"] == "Best Buy Canada"
        assert partner["location"] == "Vancouver - BC"
        assert partner["is_partner"] is True
        assert "jobillico.com/see-partner-offer/21989278" in partner["url"]
        assert "Best Buy" in partner["description"]
        # Posted date: 5 day(s) ago
        assert partner["posted_date"] is not None
        delta = datetime.now() - partner["posted_date"]
        assert 4 < delta.total_seconds() / 86400 < 6

    def test_native_listing(self) -> None:
        """Native listing (index 1) — all fields including work_type."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        native = results[1]
        assert native["job_id"] == "16720230"
        assert native["title"] == "AI Chief Developer"
        assert native["company"] == "National Bank"
        assert native["location"] == "Montreal - QC"
        assert native["work_type"] == "Full time"
        assert native["is_partner"] is False
        assert "jobillico.com/en/job-offer/national-bank/ai-chief-developer/16720230" in native["url"]
        assert "Senior Developer" in native["description"]

    def test_third_listing(self) -> None:
        """Third listing (index 2) — fields and 30+ day(s) posted date."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        third = results[2]
        assert third["job_id"] == "16406122"
        assert third["title"] == "Power BI Developer"
        assert third["company"] == "BRP"
        assert third["location"] == "Sherbrooke - QC"
        assert "Power BI" in third["description"]
        assert third["posted_date"] is not None

    def test_invariants_across_all_listings(self) -> None:
        """Properties that must hold for every listing."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        # Unique job IDs
        ids = [r["job_id"] for r in results]
        assert len(ids) == len(set(ids))
        # No tracking query params in URLs
        for r in results:
            assert "?" not in r["url"]
            assert "lshs=" not in r["url"]

    @pytest.mark.parametrize(
        "html",
        [SEARCH_RESULTS_EMPTY_HTML, SEARCH_RESULTS_NO_CONTAINER_HTML],
        ids=["empty_container", "no_container"],
    )
    def test_returns_empty_for_missing_listings(self, html: str) -> None:
        assert parse_search_results(html) == []


# ---------------------------------------------------------------------------
# JobillicoSource class
# ---------------------------------------------------------------------------


class TestJobillicoSource:
    def test_name(self) -> None:
        source = JobillicoSource()
        assert source.name == "jobillico"

    async def test_empty_keywords_returns_empty(self) -> None:
        source = JobillicoSource()
        result = await source.scrape(SearchQuery(keywords=[]))
        assert result == []

    async def test_scrape_returns_complete_opportunities(self) -> None:
        """Full scrape flow: checks count, types, source field, and all
        fields for both partner and native listings."""
        source = JobillicoSource()

        with mock_jobillico_http(SEARCH_RESULTS_HTML):
            results = await source.scrape(
                SearchQuery(keywords=["python", "developer"], location="Montreal")
            )

        # Overall checks
        assert len(results) == 3
        assert all(isinstance(r, Opportunity) for r in results)
        assert all(r.source == "jobillico" for r in results)

        # Partner listing (index 0)
        partner = results[0]
        assert partner.title == "SailPoint Developer"
        assert partner.company == "Best Buy Canada"
        assert partner.raw_data["is_partner"] is True

        # Native listing (index 1) — most complete data
        native = results[1]
        assert native.company == "National Bank"
        assert native.title == "AI Chief Developer"
        assert native.description  # not empty
        assert native.source_url  # not empty
        assert "jobillico.com" in native.source_url
        assert native.location == "Montreal - QC"
        assert native.scraped_at is not None
        assert native.raw_data is not None
        assert native.raw_data["job_id"] == "16720230"
        assert native.raw_data["work_type"] == "Full time"
        assert native.raw_data["is_partner"] is False

    async def test_respects_max_results(self) -> None:
        """Only return up to max_results opportunities."""
        source = JobillicoSource()

        with mock_jobillico_http(SEARCH_RESULTS_HTML):
            results = await source.scrape(
                SearchQuery(keywords=["developer"], max_results=1)
            )

        assert len(results) == 1

    async def test_scrape_and_persist_deduplicates(self, tmp_path: Path) -> None:
        """scrape_and_persist should not save duplicates."""
        source = JobillicoSource()
        db_conn = init_db(tmp_path / "test.db")

        with mock_jobillico_http(SEARCH_RESULTS_HTML):
            saved_first = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        # Create applications so dedup considers them active
        for opp in saved_first:
            save_application(db_conn, Application(
                opportunity_id=opp.id,
                status=ApplicationStatus.SCORED,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ))

        # Run again — same results should be deduped
        with mock_jobillico_http(SEARCH_RESULTS_HTML):
            saved_second = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        assert len(saved_first) == 3
        assert len(saved_second) == 0  # all dupes
        assert len(list_opportunities(db_conn, source="jobillico")) == 3

        db_conn.close()


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------


class TestSourceRegistration:
    def test_jobillico_in_available_sources(self) -> None:
        from emplaiyed.sources import get_available_sources

        sources = get_available_sources()
        assert "jobillico" in sources
        assert isinstance(sources["jobillico"], JobillicoSource)


# ---------------------------------------------------------------------------
# Integration test (requires network)
# ---------------------------------------------------------------------------

_has_network = os.environ.get("EMPLAIYED_TEST_NETWORK", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.mark.skipif(
    not _has_network, reason="Set EMPLAIYED_TEST_NETWORK=1 to run network tests"
)
class TestJobillicoIntegration:
    """Integration tests that hit the real jobillico.com site.

    These are skipped by default. Run with:
        EMPLAIYED_TEST_NETWORK=1 uv run pytest tests/test_sources/test_jobillico.py -k integration
    """

    async def test_real_search(self) -> None:
        source = JobillicoSource()
        results = await source.scrape(
            SearchQuery(
                keywords=["software developer"],
                location="montreal",
                max_results=5,
            )
        )
        # We expect at least some results for "software developer" in Montreal
        assert len(results) > 0
        for opp in results:
            assert opp.source == "jobillico"
            assert opp.company
            assert opp.title
            assert opp.description
            assert opp.source_url
            assert "jobillico.com" in opp.source_url
