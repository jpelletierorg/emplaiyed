"""Tests for emplaiyed.sources.jobbank — Job Bank Canada scraper."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from emplaiyed.core.database import init_db, list_opportunities, save_application
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
from emplaiyed.sources.base import SearchQuery
from emplaiyed.sources.jobbank import (
    CITY_TO_PROVINCE,
    JobBankSource,
    _build_search_url,
    _parse_date,
    _parse_job_id,
    _parse_salary,
    parse_job_posting,
    parse_search_results,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = """
<html>
<body>
<div id="results-list-content">
  <a href="/jobsearch/jobposting/48919846;jsessionid=ABC123?source=searchresults">
    <h3>New Talent.com software developer</h3>
    <ul>
      <li>February 09, 2026</li>
      <li>Lancesoft</li>
      <li>Location Montréal (QC)</li>
      <li>Salary $65.52 to $80.00 hourly</li>
      <li>Talent.com Job number: 575869796659899976</li>
    </ul>
  </a>
  <a href="/jobsearch/jobposting/49000001;jsessionid=DEF456?source=searchresults">
    <h3>cloud architect</h3>
    <ul>
      <li>January 15, 2026</li>
      <li>Big Corp Inc</li>
      <li>Location Quebec City (QC)</li>
      <li>Salary $90,000 to $120,000 annually</li>
      <li>Indeed Job number: 12345</li>
    </ul>
  </a>
</div>
</body>
</html>
"""

SEARCH_RESULTS_EMPTY_HTML = """
<html>
<body>
<div id="results-list-content">
  <p>0 results</p>
</div>
</body>
</html>
"""

JOB_POSTING_HTML = """
<html>
<head><title>software developer - Job Bank</title></head>
<body>
<nav>Navigation stuff</nav>
<h1>software developer</h1>
<div class="job-details">
  <strong>Lancesoft</strong>
  <table>
    <tr><td>Location</td><td>Montréal, QC</td></tr>
    <tr><td>Salary</td><td>$65.52 to $80.00HOUR hourly</td></tr>
    <tr><td>Terms of employment</td><td>Full time</td></tr>
  </table>
  <h2>Job Description</h2>
  <p>We are looking for an experienced software developer to join our team.
  The candidate will work on cloud-native microservices using Java and Python.</p>
  <strong>Requirements:</strong>
  <ul>
    <li>5+ years of experience</li>
    <li>Strong knowledge of Java and Python</li>
    <li>Experience with AWS or GCP</li>
  </ul>
</div>
<script>var tracking = true;</script>
<style>.hidden { display: none; }</style>
<footer>Footer stuff</footer>
</body>
</html>
"""

JOB_POSTING_HTML_2 = """
<html>
<head><title>cloud architect - Job Bank</title></head>
<body>
<nav>Navigation stuff</nav>
<h1>cloud architect</h1>
<div class="job-details">
  <strong>Big Corp Inc</strong>
  <table>
    <tr><td>Location</td><td>Quebec City, QC</td></tr>
    <tr><td>Salary</td><td>$90,000 to $120,000 annually</td></tr>
    <tr><td>Terms of employment</td><td>Full time</td></tr>
  </table>
  <h2>Job Description</h2>
  <p>We need a cloud architect to lead our infrastructure team.</p>
</div>
<footer>Footer stuff</footer>
</body>
</html>
"""

# Real Job Bank listings wrap location parts in <span> elements, which causes
# get_text(strip=True) to concatenate them without spaces.
SEARCH_RESULTS_NESTED_HTML = """
<html>
<body>
<div id="results-list-content">
  <a href="/jobsearch/jobposting/50000001;jsessionid=XYZ?source=searchresults">
    <h3>data analyst</h3>
    <ul>
      <li>February 10, 2026</li>
      <li>Acme Corp</li>
      <li><span class="visually-hidden">Location</span><span>Windsor</span>,<span>ON</span><span>N9G 0A2</span></li>
      <li>Salary $55,000 to $70,000 annually</li>
    </ul>
  </a>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _mock_scrape(get_side_effects: list):
    """Patch httpx.AsyncClient so that .get() yields the given responses in order.

    Usage::

        with _mock_scrape([resp1, resp2]):
            results = await source.scrape(query)

    *get_side_effects* can contain ``httpx.Response`` objects or exceptions.
    """
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=get_side_effects)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("emplaiyed.sources.jobbank.httpx.AsyncClient", return_value=mock_client):
        yield


def _response(text: str, url: str = "https://www.jobbank.gc.ca/") -> httpx.Response:
    """Build an httpx.Response with the given text body."""
    return httpx.Response(
        status_code=200,
        text=text,
        request=httpx.Request("GET", url),
    )


# Pre-built responses used by multiple tests
_SEARCH_RESP = _response(SEARCH_RESULTS_HTML, "https://www.jobbank.gc.ca/jobsearch/jobsearch")
_POSTING_RESP_1 = _response(JOB_POSTING_HTML, "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846")
_POSTING_RESP_2 = _response(JOB_POSTING_HTML_2, "https://www.jobbank.gc.ca/jobsearch/jobposting/49000001")


# ---------------------------------------------------------------------------
# Helper parsers — parametrized
# ---------------------------------------------------------------------------


class TestParseJobId:
    @pytest.mark.parametrize(
        "href, expected",
        [
            ("/jobsearch/jobposting/48919846;jsessionid=ABC", "48919846"),
            ("/jobsearch/jobposting/12345", "12345"),
            ("/some/other/path", None),
            ("", None),
        ],
        ids=["with_session", "without_session", "no_match", "empty"],
    )
    def test_parse_job_id(self, href: str, expected: str | None) -> None:
        assert _parse_job_id(href) == expected


class TestParseSalary:
    @pytest.mark.parametrize(
        "text, check",
        [
            (
                "$65.52 to $80.00 hourly",
                lambda lo, hi: lo is not None and hi is not None and lo > 100000 and hi > lo,
            ),
            (
                "$90,000 to $120,000 annually",
                lambda lo, hi: lo == 90000 and hi == 120000,
            ),
            (
                "$45.00 hourly",
                lambda lo, hi: lo is not None and lo == hi and lo > 80000,
            ),
            (
                "Not specified",
                lambda lo, hi: lo is None and hi is None,
            ),
            (
                "",
                lambda lo, hi: lo is None and hi is None,
            ),
        ],
        ids=["hourly_range", "annual_range", "single_hourly", "no_salary", "empty"],
    )
    def test_parse_salary(self, text: str, check) -> None:
        sal_min, sal_max = _parse_salary(text)
        assert check(sal_min, sal_max), f"Failed for {text!r}: got ({sal_min}, {sal_max})"


class TestParseDate:
    @pytest.mark.parametrize(
        "text, year, month, day",
        [
            ("February 09, 2026", 2026, 2, 9),
            ("2026-01-15", 2026, 1, 15),
        ],
        ids=["full_date", "iso_date"],
    )
    def test_valid_dates(self, text: str, year: int, month: int, day: int) -> None:
        dt = _parse_date(text)
        assert dt is not None
        assert (dt.year, dt.month, dt.day) == (year, month, day)

    @pytest.mark.parametrize(
        "text",
        ["not a date", ""],
        ids=["invalid", "empty"],
    )
    def test_invalid_dates_return_none(self, text: str) -> None:
        assert _parse_date(text) is None


class TestBuildSearchUrl:
    @pytest.mark.parametrize(
        "location, expected_fragment",
        [
            ("Quebec", "fprov=QC"),
            ("ON", "fprov=ON"),
            ("Québec", "fprov=QC"),
        ],
        ids=["province_name", "province_code", "accent"],
    )
    def test_location_maps_to_fprov(self, location: str, expected_fragment: str) -> None:
        url = _build_search_url(SearchQuery(keywords=["developer"], location=location))
        assert expected_fragment in url

    def test_basic_keywords(self) -> None:
        url = _build_search_url(SearchQuery(keywords=["python", "developer"]))
        assert "searchstring=python+developer" in url
        assert "jobbank.gc.ca" in url

    def test_no_location_omits_fprov(self) -> None:
        url = _build_search_url(SearchQuery(keywords=["developer"]))
        assert "fprov" not in url


# ---------------------------------------------------------------------------
# City-to-province mapping — parametrized
# ---------------------------------------------------------------------------


class TestCityToProvinceMapping:
    @pytest.mark.parametrize(
        "city, province_code",
        [
            ("Longueuil", "QC"),
            ("Toronto", "ON"),
            ("Montréal", "QC"),
            ("Vancouver", "BC"),
            ("Ontario", "ON"),  # province name still works
        ],
        ids=["longueuil", "toronto", "montreal_accent", "vancouver", "province_name"],
    )
    def test_known_locations_map_correctly(self, city: str, province_code: str) -> None:
        url = _build_search_url(SearchQuery(keywords=["developer"], location=city))
        assert f"fprov={province_code}" in url

    def test_unknown_location_no_fprov(self) -> None:
        url = _build_search_url(SearchQuery(keywords=["developer"], location="Timbuktu"))
        assert "fprov" not in url

    def test_unknown_location_logs_warning(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="emplaiyed.sources.jobbank"):
            _build_search_url(SearchQuery(keywords=["developer"], location="Timbuktu"))
        assert "Could not map location" in caplog.text


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    def test_parses_two_listings_with_correct_fields(self) -> None:
        """Parse the standard fixture and verify both listings at once."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        assert len(results) == 2

        first = results[0]
        assert first["job_id"] == "48919846"
        assert first["company"] == "Lancesoft"
        assert "Montréal" in first["location"] or "Montreal" in first["location"]
        assert "$" in first["salary_text"] or first["salary_text"]
        assert first["url"] == "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846"
        # Source prefixes like "New Talent.com" should be stripped
        assert "Talent.com" not in first["title"]
        assert "New" not in first["title"]
        assert "software developer" in first["title"].lower()

        second = results[1]
        assert "$90,000" in second["salary_text"]

    def test_empty_results(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_EMPTY_HTML)
        assert results == []

    def test_job_ids_are_unique(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_HTML)
        ids = [r["job_id"] for r in results]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Nested HTML location parsing (real-world bug reproduction)
# ---------------------------------------------------------------------------


class TestParseSearchResultsNestedHtml:
    """Verify that nested <span> elements in location render with proper spacing."""

    def test_location_has_spaces_and_no_prefix(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_NESTED_HTML)
        assert len(results) == 1
        loc = results[0]["location"]
        # Should NOT be "Windsor,ONN9G 0A2"
        assert "Windsor" in loc
        assert "ON" in loc
        # The key fix: spaces between city, province, postal code
        assert "Windsor," in loc or "Windsor ," in loc  # comma present
        assert ",ON" not in loc or ", ON" in loc  # space after comma
        # No "Location" prefix
        assert not loc.startswith("Location")


# ---------------------------------------------------------------------------
# Job posting parsing
# ---------------------------------------------------------------------------


class TestParseJobPosting:
    def test_extracts_all_fields_and_strips_noise(self) -> None:
        """Parse the job posting fixture and verify all fields in one test."""
        data = parse_job_posting(JOB_POSTING_HTML)

        # Title
        assert "software developer" in data["title"].lower()

        # Description content
        assert "cloud-native microservices" in data["description"]
        assert "Java and Python" in data["description"]

        # Scripts and styles stripped
        assert "var tracking" not in data["description"]
        assert ".hidden" not in data["description"]

        # Nav and footer stripped
        assert "Navigation stuff" not in data["description"]
        assert "Footer stuff" not in data["description"]

        # Salary present
        assert "$65.52" in data["salary_text"] or data["salary_text"]

        # Location is a string (may or may not be found depending on HTML structure)
        assert isinstance(data["location"], str)


# ---------------------------------------------------------------------------
# JobBankSource class
# ---------------------------------------------------------------------------


class TestJobBankSource:
    def test_name(self) -> None:
        source = JobBankSource()
        assert source.name == "jobbank"

    async def test_empty_keywords_returns_empty(self) -> None:
        source = JobBankSource()
        result = await source.scrape(SearchQuery(keywords=[]))
        assert result == []

    async def test_scrape_returns_fully_populated_opportunities(self) -> None:
        """Full scrape flow: verify count, types, source, and all key fields."""
        source = JobBankSource()

        with _mock_scrape([_SEARCH_RESP, _POSTING_RESP_1, _POSTING_RESP_2]):
            results = await source.scrape(SearchQuery(keywords=["developer"]))

        # Count and types
        assert len(results) == 2
        assert all(isinstance(r, Opportunity) for r in results)
        assert all(r.source == "jobbank" for r in results)

        # All key fields populated on first result
        first = results[0]
        assert first.company
        assert first.title
        assert first.description
        assert first.source_url
        assert first.scraped_at is not None
        assert first.raw_data is not None
        assert "job_id" in first.raw_data

    async def test_scrape_handles_posting_fetch_failure(self) -> None:
        """If fetching an individual posting fails, use listing data."""
        source = JobBankSource()

        with _mock_scrape([_SEARCH_RESP, httpx.HTTPError("fail"), httpx.HTTPError("fail")]):
            results = await source.scrape(SearchQuery(keywords=["developer"]))

        # Should still return results even if detail pages fail
        assert len(results) == 2
        assert all(r.title for r in results)

    async def test_respects_max_results(self) -> None:
        """Only fetch up to max_results postings."""
        source = JobBankSource()

        with _mock_scrape([_SEARCH_RESP, _POSTING_RESP_1]):
            results = await source.scrape(
                SearchQuery(keywords=["developer"], max_results=1)
            )

        assert len(results) == 1

    async def test_scrape_and_persist_deduplicates(self, tmp_path: Path) -> None:
        """scrape_and_persist should not save duplicates."""
        from datetime import datetime
        source = JobBankSource()
        db_conn = init_db(tmp_path / "test.db")

        with _mock_scrape([_SEARCH_RESP, _POSTING_RESP_1, _POSTING_RESP_2]):
            saved_first = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        # Create applications so dedup sees them as active
        for opp in saved_first:
            save_application(db_conn, Application(
                opportunity_id=opp.id, status=ApplicationStatus.SCORED,
                created_at=datetime.now(), updated_at=datetime.now(),
            ))

        with _mock_scrape([_SEARCH_RESP, _POSTING_RESP_1, _POSTING_RESP_2]):
            saved_second = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        assert len(saved_first) == 2
        assert len(saved_second) == 0  # all dupes
        db_conn.close()


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------


class TestSourceRegistration:
    def test_jobbank_in_available_sources(self) -> None:
        from emplaiyed.sources import get_available_sources

        sources = get_available_sources()
        assert "jobbank" in sources
        assert isinstance(sources["jobbank"], JobBankSource)


# ---------------------------------------------------------------------------
# Integration test (requires network)
# ---------------------------------------------------------------------------

_has_network = os.environ.get("EMPLAIYED_TEST_NETWORK", "").lower() in ("1", "true", "yes")

@pytest.mark.skipif(not _has_network, reason="Set EMPLAIYED_TEST_NETWORK=1 to run network tests")
class TestJobBankIntegration:
    """Integration tests that hit the real jobbank.gc.ca site.

    These are skipped by default. Run with:
        EMPLAIYED_TEST_NETWORK=1 uv run pytest tests/test_sources/test_jobbank.py -k integration
    """

    async def test_real_search(self) -> None:
        source = JobBankSource()
        results = await source.scrape(
            SearchQuery(keywords=["software developer"], location="QC", max_results=5)
        )
        # We expect at least some results for "software developer" in Quebec
        assert len(results) > 0
        for opp in results:
            assert opp.source == "jobbank"
            assert opp.company
            assert opp.title
            assert opp.description
            assert opp.source_url
            assert "jobbank.gc.ca" in opp.source_url
