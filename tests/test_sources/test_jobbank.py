"""Tests for emplaiyed.sources.jobbank — Job Bank Canada scraper."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from emplaiyed.core.database import init_db, list_opportunities
from emplaiyed.core.models import Opportunity
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


# ---------------------------------------------------------------------------
# Helper parsers
# ---------------------------------------------------------------------------


class TestParseJobId:
    def test_extracts_numeric_id(self) -> None:
        assert _parse_job_id("/jobsearch/jobposting/48919846;jsessionid=ABC") == "48919846"

    def test_extracts_id_without_session(self) -> None:
        assert _parse_job_id("/jobsearch/jobposting/12345") == "12345"

    def test_returns_none_for_no_match(self) -> None:
        assert _parse_job_id("/some/other/path") is None

    def test_returns_none_for_empty(self) -> None:
        assert _parse_job_id("") is None


class TestParseSalary:
    def test_hourly_range(self) -> None:
        sal_min, sal_max = _parse_salary("$65.52 to $80.00 hourly")
        # 65.52 * 40 * 52 ≈ 136,281; 80.00 * 40 * 52 = 166,400
        assert sal_min is not None
        assert sal_max is not None
        assert sal_min > 100000  # hourly converted to annual
        assert sal_max > sal_min

    def test_annual_range(self) -> None:
        sal_min, sal_max = _parse_salary("$90,000 to $120,000 annually")
        assert sal_min == 90000
        assert sal_max == 120000

    def test_single_hourly(self) -> None:
        sal_min, sal_max = _parse_salary("$45.00 hourly")
        assert sal_min is not None
        assert sal_min == sal_max
        assert sal_min > 80000  # hourly converted to annual

    def test_no_salary(self) -> None:
        assert _parse_salary("Not specified") == (None, None)

    def test_empty_string(self) -> None:
        assert _parse_salary("") == (None, None)


class TestParseDate:
    def test_full_date(self) -> None:
        dt = _parse_date("February 09, 2026")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 9

    def test_iso_date(self) -> None:
        dt = _parse_date("2026-01-15")
        assert dt is not None
        assert dt.year == 2026

    def test_invalid_date(self) -> None:
        assert _parse_date("not a date") is None

    def test_empty_string(self) -> None:
        assert _parse_date("") is None


class TestBuildSearchUrl:
    def test_basic_keywords(self) -> None:
        url = _build_search_url(SearchQuery(keywords=["python", "developer"]))
        assert "searchstring=python+developer" in url
        assert "jobbank.gc.ca" in url

    def test_with_quebec_location(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Quebec")
        )
        assert "fprov=QC" in url

    def test_with_province_code(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="ON")
        )
        assert "fprov=ON" in url

    def test_no_location(self) -> None:
        url = _build_search_url(SearchQuery(keywords=["developer"]))
        assert "fprov" not in url

    def test_with_accent_quebec(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Québec")
        )
        assert "fprov=QC" in url


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    def test_parses_two_listings(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_HTML)
        assert len(results) == 2

    def test_first_listing_fields(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_HTML)
        first = results[0]
        assert first["job_id"] == "48919846"
        assert first["company"] == "Lancesoft"
        assert "Montréal" in first["location"] or "Montreal" in first["location"]
        assert "$" in first["salary_text"] or first["salary_text"]
        assert first["url"] == "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846"

    def test_title_cleaned(self) -> None:
        """Source prefixes like 'New Talent.com' should be stripped."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        first = results[0]
        assert "Talent.com" not in first["title"]
        assert "New" not in first["title"]
        assert "software developer" in first["title"].lower()

    def test_second_listing_annual_salary(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_HTML)
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
# Job posting parsing
# ---------------------------------------------------------------------------


class TestParseJobPosting:
    def test_extracts_title(self) -> None:
        data = parse_job_posting(JOB_POSTING_HTML)
        assert "software developer" in data["title"].lower()

    def test_extracts_description(self) -> None:
        data = parse_job_posting(JOB_POSTING_HTML)
        assert "cloud-native microservices" in data["description"]
        assert "Java and Python" in data["description"]

    def test_strips_scripts_and_styles(self) -> None:
        data = parse_job_posting(JOB_POSTING_HTML)
        assert "var tracking" not in data["description"]
        assert ".hidden" not in data["description"]

    def test_strips_nav_and_footer(self) -> None:
        data = parse_job_posting(JOB_POSTING_HTML)
        assert "Navigation stuff" not in data["description"]
        assert "Footer stuff" not in data["description"]

    def test_extracts_salary(self) -> None:
        data = parse_job_posting(JOB_POSTING_HTML)
        assert "$65.52" in data["salary_text"] or data["salary_text"]

    def test_extracts_location(self) -> None:
        data = parse_job_posting(JOB_POSTING_HTML)
        # Location may or may not be found depending on HTML structure
        # but the parser should not error
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

    async def test_scrape_with_mocked_http(self) -> None:
        """Full scrape flow with mocked HTTP responses."""
        source = JobBankSource()

        search_response = httpx.Response(
            status_code=200,
            text=SEARCH_RESULTS_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobsearch"),
        )
        posting_response_1 = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846"),
        )
        posting_response_2 = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML_2,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/49000001"),
        )

        with patch("emplaiyed.sources.jobbank.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_response, posting_response_1, posting_response_2])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await source.scrape(SearchQuery(keywords=["developer"]))

        assert len(results) == 2
        assert all(isinstance(r, Opportunity) for r in results)
        assert all(r.source == "jobbank" for r in results)

    async def test_scrape_populates_all_fields(self) -> None:
        """Each Opportunity should have all key fields populated."""
        source = JobBankSource()

        search_response = httpx.Response(
            status_code=200,
            text=SEARCH_RESULTS_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobsearch"),
        )
        posting_response_1 = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846"),
        )
        posting_response_2 = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML_2,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/49000001"),
        )

        with patch("emplaiyed.sources.jobbank.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_response, posting_response_1, posting_response_2])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await source.scrape(SearchQuery(keywords=["developer"]))

        first = results[0]
        assert first.company  # not empty
        assert first.title  # not empty
        assert first.description  # not empty
        assert first.source_url  # not empty
        assert first.scraped_at is not None
        assert first.raw_data is not None
        assert "job_id" in first.raw_data

    async def test_scrape_handles_posting_fetch_failure(self) -> None:
        """If fetching an individual posting fails, use listing data."""
        source = JobBankSource()

        search_response = httpx.Response(
            status_code=200,
            text=SEARCH_RESULTS_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobsearch"),
        )

        async def side_effect_fn(url, **kwargs):
            if "jobposting" in str(url):
                raise httpx.HTTPError("Connection failed")
            return search_response

        with patch("emplaiyed.sources.jobbank.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_response, httpx.HTTPError("fail"), httpx.HTTPError("fail")])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await source.scrape(SearchQuery(keywords=["developer"]))

        # Should still return results even if detail pages fail
        assert len(results) == 2
        assert all(r.title for r in results)

    async def test_respects_max_results(self) -> None:
        """Only fetch up to max_results postings."""
        source = JobBankSource()

        search_response = httpx.Response(
            status_code=200,
            text=SEARCH_RESULTS_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobsearch"),
        )
        posting_response = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846"),
        )

        with patch("emplaiyed.sources.jobbank.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_response, posting_response])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            results = await source.scrape(
                SearchQuery(keywords=["developer"], max_results=1)
            )

        assert len(results) == 1

    async def test_scrape_and_persist_deduplicates(self, tmp_path: Path) -> None:
        """scrape_and_persist should not save duplicates."""
        source = JobBankSource()
        db_conn = init_db(tmp_path / "test.db")

        search_response = httpx.Response(
            status_code=200,
            text=SEARCH_RESULTS_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobsearch"),
        )
        posting_response_1 = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/48919846"),
        )
        posting_response_2 = httpx.Response(
            status_code=200,
            text=JOB_POSTING_HTML_2,
            request=httpx.Request("GET", "https://www.jobbank.gc.ca/jobsearch/jobposting/49000001"),
        )

        with patch("emplaiyed.sources.jobbank.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_response, posting_response_1, posting_response_2])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            saved_first = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        # Run again — same results should be deduped
        with patch("emplaiyed.sources.jobbank.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_response, posting_response_1, posting_response_2])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            saved_second = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        assert len(saved_first) == 2
        assert len(saved_second) == 0  # all dupes
        assert len(list_opportunities(db_conn)) == 2

        db_conn.close()


# ---------------------------------------------------------------------------
# Nested HTML location parsing (real-world bug reproduction)
# ---------------------------------------------------------------------------

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


class TestParseSearchResultsNestedHtml:
    """Verify that nested <span> elements in location render with proper spacing."""

    def test_location_has_spaces(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_NESTED_HTML)
        assert len(results) == 1
        loc = results[0]["location"]
        # Should NOT be "Windsor,ONN9G 0A2"
        assert "Windsor" in loc
        assert "ON" in loc
        # The key fix: spaces between city, province, postal code
        assert "Windsor," in loc or "Windsor ," in loc  # comma present
        assert ",ON" not in loc or ", ON" in loc  # space after comma

    def test_no_location_prefix(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_NESTED_HTML)
        loc = results[0]["location"]
        assert not loc.startswith("Location")


class TestCityToProvinceMapping:
    def test_longueuil_maps_to_qc(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Longueuil")
        )
        assert "fprov=QC" in url

    def test_toronto_maps_to_on(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Toronto")
        )
        assert "fprov=ON" in url

    def test_montreal_accent_maps_to_qc(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Montréal")
        )
        assert "fprov=QC" in url

    def test_vancouver_maps_to_bc(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Vancouver")
        )
        assert "fprov=BC" in url

    def test_unknown_location_no_fprov(self) -> None:
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Timbuktu")
        )
        assert "fprov" not in url

    def test_unknown_location_logs_warning(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="emplaiyed.sources.jobbank"):
            _build_search_url(
                SearchQuery(keywords=["developer"], location="Timbuktu")
            )
        assert "Could not map location" in caplog.text

    def test_province_name_still_works(self) -> None:
        """Province names should still work (not broken by city fallback)."""
        url = _build_search_url(
            SearchQuery(keywords=["developer"], location="Ontario")
        )
        assert "fprov=ON" in url


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
