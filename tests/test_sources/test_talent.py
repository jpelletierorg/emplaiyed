"""Tests for emplaiyed.sources.talent -- Talent.com job aggregator scraper."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from emplaiyed.core.database import init_db, list_opportunities, save_application
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
from emplaiyed.sources.base import SearchQuery
from emplaiyed.sources.talent import (
    TalentSource,
    _build_search_url,
    _extract_company,
    _extract_job_id,
    _extract_location,
    _parse_date,
    _parse_salary,
    extract_jsonld_jobs,
    parse_search_results,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = """
<html>
<head>
<title>Python Developer Jobs in Montreal - Talent.com</title>
<script type="application/ld+json">
[
  {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior Python Developer",
    "description": "<p>We are looking for a Senior Python Developer to join our team. You will build scalable microservices and work with cloud technologies.</p><ul><li>5+ years Python experience</li><li>AWS or GCP knowledge</li></ul>",
    "identifier": {
      "@type": "PropertyValue",
      "name": "Talent.com",
      "value": "job-abc-123"
    },
    "datePosted": "2026-02-10",
    "hiringOrganization": {
      "@type": "Organization",
      "name": "TechCorp Inc"
    },
    "jobLocation": {
      "@type": "Place",
      "address": {
        "@type": "PostalAddress",
        "addressLocality": "Montreal",
        "addressRegion": "QC",
        "addressCountry": "CA"
      }
    },
    "baseSalary": {
      "@type": "MonetaryAmount",
      "currency": "CAD",
      "value": {
        "@type": "QuantitativeValue",
        "minValue": 95000,
        "maxValue": 130000,
        "unitText": "YEAR"
      },
      "unitText": "YEAR"
    },
    "url": "https://www.talent.com/view?id=abc123"
  },
  {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Python Backend Engineer",
    "description": "Join our backend team to develop APIs and data pipelines using Python and Django.",
    "identifier": {
      "@type": "PropertyValue",
      "name": "Talent.com",
      "value": "job-def-456"
    },
    "datePosted": "2026-02-08T14:30:00Z",
    "hiringOrganization": {
      "@type": "Organization",
      "name": "DataFlow Systems"
    },
    "jobLocation": {
      "@type": "Place",
      "address": {
        "@type": "PostalAddress",
        "addressLocality": "Laval",
        "addressRegion": "QC",
        "addressCountry": "CA"
      }
    },
    "baseSalary": {
      "@type": "MonetaryAmount",
      "currency": "CAD",
      "value": {
        "@type": "QuantitativeValue",
        "minValue": 45,
        "maxValue": 55,
        "unitText": "HOUR"
      },
      "unitText": "HOUR"
    },
    "url": "https://www.talent.com/view?id=def456"
  }
]
</script>
</head>
<body>
<div id="app"></div>
</body>
</html>
"""

SEARCH_RESULTS_GRAPH_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "JobPosting",
      "title": "DevOps Engineer",
      "description": "Manage CI/CD pipelines and cloud infrastructure.",
      "identifier": "devops-001",
      "datePosted": "2026-02-12",
      "hiringOrganization": {
        "@type": "Organization",
        "name": "CloudOps Ltd"
      },
      "jobLocation": {
        "@type": "Place",
        "address": {
          "@type": "PostalAddress",
          "addressLocality": "Toronto",
          "addressRegion": "ON"
        }
      },
      "url": "https://www.talent.com/view?id=devops001"
    }
  ]
}
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_SINGLE_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Data Scientist",
  "description": "Apply ML models to business problems.",
  "identifier": {
    "@type": "PropertyValue",
    "value": "ds-789"
  },
  "datePosted": "2026-01-20",
  "hiringOrganization": "Startup AI",
  "jobLocation": "Montreal, QC",
  "baseSalary": "$90,000 - $120,000",
  "url": "https://www.talent.com/view?id=ds789"
}
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_NO_JSONLD_HTML = """
<html>
<head><title>No results</title></head>
<body><div id="app"></div></body>
</html>
"""

SEARCH_RESULTS_EMPTY_JSONLD_HTML = """
<html>
<head>
<script type="application/ld+json">[]</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_NON_JOB_JSONLD_HTML = """
<html>
<head>
<script type="application/ld+json">
{"@type": "WebSite", "name": "Talent.com", "url": "https://www.talent.com"}
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_MALFORMED_JSON_HTML = """
<html>
<head>
<script type="application/ld+json">
{ this is not valid json }
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_DUPLICATE_HTML = """
<html>
<head>
<script type="application/ld+json">
[
  {"@type": "JobPosting", "title": "Duplicate Job", "description": "First.", "identifier": {"value": "dup-001"}, "hiringOrganization": {"name": "DupCorp"}, "url": "https://www.talent.com/view?id=dup1"},
  {"@type": "JobPosting", "title": "Duplicate Job", "description": "Second.", "identifier": {"value": "dup-001"}, "hiringOrganization": {"name": "DupCorp"}, "url": "https://www.talent.com/view?id=dup2"},
  {"@type": "JobPosting", "title": "Unique Job", "description": "Different.", "identifier": {"value": "unique-002"}, "hiringOrganization": {"name": "UniqueCorp"}, "url": "https://www.talent.com/view?id=unique2"}
]
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_NO_SALARY_HTML = """
<html>
<head>
<script type="application/ld+json">
[{"@type": "JobPosting", "title": "Junior Developer", "description": "Entry level.", "identifier": {"value": "jr-001"}, "hiringOrganization": {"name": "SmallCo"}, "jobLocation": {"@type": "Place", "address": {"addressLocality": "Quebec City", "addressRegion": "QC"}}, "url": "https://www.talent.com/view?id=jr001"}]
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_PAGE2_HTML = """
<html>
<head>
<script type="application/ld+json">
[{"@type": "JobPosting", "title": "Page 2 Job", "description": "Second page.", "identifier": {"value": "p2-001"}, "hiringOrganization": {"name": "Page2Corp"}, "url": "https://www.talent.com/view?id=p2001"}]
</script>
</head>
<body></body>
</html>
"""

SEARCH_RESULTS_HTML_DESC = """
<html>
<head>
<script type="application/ld+json">
[{"@type": "JobPosting", "title": "Frontend Developer", "description": "<div><h2>About the Role</h2><p>Build amazing UIs with <strong>React</strong> and TypeScript.</p><ul><li>3+ years experience</li><li>CSS expertise</li></ul></div>", "identifier": {"value": "fe-001"}, "hiringOrganization": {"name": "WebAgency"}, "url": "https://www.talent.com/view?id=fe001"}]
</script>
</head>
<body></body>
</html>
"""


# ---------------------------------------------------------------------------
# Helper: mock HTTP for TalentSource.scrape()
# ---------------------------------------------------------------------------

def _mock_talent_scrape(responses: list[httpx.Response]):
    """Context manager that patches httpx.AsyncClient for TalentSource tests."""
    mock_client_cls = patch("emplaiyed.sources.talent.httpx.AsyncClient")
    mock_cm = mock_client_cls.start()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_cm.return_value = mock_client
    return mock_client_cls


def _response(text: str, url: str = "https://www.talent.com/jobs") -> httpx.Response:
    return httpx.Response(status_code=200, text=text, request=httpx.Request("GET", url))


# ---------------------------------------------------------------------------
# Helper function tests (parametrized)
# ---------------------------------------------------------------------------


class TestBuildSearchUrl:
    @pytest.mark.parametrize("query,page,expected,not_expected", [
        (SearchQuery(keywords=["python", "developer"]), 0, ["talent.com/jobs", "k=python+developer"], []),
        (SearchQuery(keywords=["developer"], location="Montreal"), 0, ["k=developer", "l=Montreal"], []),
        (SearchQuery(keywords=["developer"], location="Montreal", radius_km=25), 0, ["r=25"], []),
        (SearchQuery(keywords=[]), 0, ["talent.com/jobs"], ["k="]),
        (SearchQuery(keywords=["developer"]), 2, ["p=2"], []),
        (SearchQuery(keywords=["developer"]), 0, [], ["p="]),
    ], ids=["basic", "location", "radius", "empty-keywords", "page2", "page0-no-p"])
    def test_url_construction(self, query, page, expected, not_expected):
        url = _build_search_url(query, page=page)
        for exp in expected:
            assert exp in url, f"Expected '{exp}' in {url}"
        for nexp in not_expected:
            assert nexp not in url, f"Unexpected '{nexp}' in {url}"


class TestParseSalary:
    @pytest.mark.parametrize("input_val,expected", [
        ({"value": {"minValue": 95000, "maxValue": 130000, "unitText": "YEAR"}, "unitText": "YEAR"}, (95000, 130000)),
        ({"value": {"minValue": 45, "maxValue": 55, "unitText": "HOUR"}, "unitText": "HOUR"}, (93600, 114400)),
        ("$90,000 - $120,000", (90000, 120000)),
        ({"value": 85000, "unitText": "YEAR"}, (85000, 85000)),
        ({"value": 50, "unitText": "HOURLY"}, (104000, 104000)),
        (None, (None, None)),
        ("", (None, None)),
        ("Competitive salary", (None, None)),
    ], ids=["annual-range", "hourly-range", "string", "single-annual", "single-hourly", "none", "empty", "no-numbers"])
    def test_parse(self, input_val, expected):
        assert _parse_salary(input_val) == expected


class TestParseDate:
    @pytest.mark.parametrize("input_val,year,month,day", [
        ("2026-02-10", 2026, 2, 10),
        ("2026-02-08T14:30:00Z", 2026, 2, 8),
        ("2026-02-08T14:30:00", 2026, 2, 8),
    ], ids=["iso-date", "iso-datetime-z", "iso-datetime"])
    def test_valid_dates(self, input_val, year, month, day):
        dt = _parse_date(input_val)
        assert dt is not None
        assert (dt.year, dt.month, dt.day) == (year, month, day)

    @pytest.mark.parametrize("input_val", [None, "", "not a date"], ids=["none", "empty", "invalid"])
    def test_invalid_returns_none(self, input_val):
        assert _parse_date(input_val) is None


class TestExtractLocation:
    @pytest.mark.parametrize("job,expected", [
        ({"jobLocation": {"@type": "Place", "address": {"addressLocality": "Montreal", "addressRegion": "QC", "addressCountry": "CA"}}}, "Montreal, QC, CA"),
        ({"jobLocation": {"@type": "Place", "address": {"addressLocality": "Toronto", "addressRegion": "ON"}}}, "Toronto, ON"),
        ({"jobLocation": "Montreal, QC"}, "Montreal, QC"),
        ({}, ""),
        ({"jobLocation": [{"@type": "Place", "address": {"addressLocality": "Vancouver", "addressRegion": "BC"}}]}, "Vancouver, BC"),
        ({"jobLocation": {"@type": "Place", "address": "123 Main St, Montreal, QC"}}, "123 Main St, Montreal, QC"),
    ], ids=["full-address", "city-region", "string", "empty", "list", "string-address"])
    def test_extract(self, job, expected):
        assert _extract_location(job) == expected


class TestExtractCompany:
    @pytest.mark.parametrize("job,expected", [
        ({"hiringOrganization": {"@type": "Organization", "name": "TechCorp"}}, "TechCorp"),
        ({"hiringOrganization": "Startup AI"}, "Startup AI"),
        ({}, "Unknown Company"),
        ({"hiringOrganization": None}, "Unknown Company"),
    ], ids=["org-dict", "string", "missing", "none"])
    def test_extract(self, job, expected):
        assert _extract_company(job) == expected


class TestExtractJobId:
    @pytest.mark.parametrize("job,expected", [
        ({"identifier": {"@type": "PropertyValue", "value": "job-abc-123"}}, "job-abc-123"),
        ({"identifier": "devops-001"}, "devops-001"),
        ({"identifier": 12345}, "12345"),
        ({"url": "https://www.talent.com/job/senior-dev-123"}, "senior-dev-123"),
        ({}, None),
    ], ids=["dict", "string", "int", "url-fallback", "nothing"])
    def test_extract(self, job, expected):
        assert _extract_job_id(job) == expected


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


class TestExtractJsonldJobs:
    def test_extracts_from_array(self):
        jobs = extract_jsonld_jobs(SEARCH_RESULTS_HTML)
        assert len(jobs) == 2
        assert jobs[0]["title"] == "Senior Python Developer"

    def test_extracts_from_graph(self):
        jobs = extract_jsonld_jobs(SEARCH_RESULTS_GRAPH_HTML)
        assert len(jobs) == 1
        assert jobs[0]["title"] == "DevOps Engineer"

    def test_extracts_single_object(self):
        jobs = extract_jsonld_jobs(SEARCH_RESULTS_SINGLE_HTML)
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Data Scientist"

    @pytest.mark.parametrize("html", [
        SEARCH_RESULTS_NO_JSONLD_HTML,
        SEARCH_RESULTS_EMPTY_JSONLD_HTML,
        SEARCH_RESULTS_NON_JOB_JSONLD_HTML,
        SEARCH_RESULTS_MALFORMED_JSON_HTML,
    ], ids=["no-jsonld", "empty", "non-job", "malformed"])
    def test_returns_empty(self, html):
        assert extract_jsonld_jobs(html) == []


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    def test_main_html_parsed_correctly(self):
        """Comprehensive check of the main 2-listing HTML fixture."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        assert len(results) == 2

        first = results[0]
        assert first["job_id"] == "job-abc-123"
        assert first["title"] == "Senior Python Developer"
        assert first["company"] == "TechCorp Inc"
        assert "Montreal" in first["location"]
        assert first["salary_min"] == 95000
        assert first["salary_max"] == 130000
        assert first["url"] == "https://www.talent.com/view?id=abc123"
        assert first["posted_date"].year == 2026
        # HTML tags stripped
        assert "<p>" not in first["description"]
        assert "5+ years Python experience" in first["description"]

        second = results[1]
        assert second["company"] == "DataFlow Systems"
        # Hourly converted: 45*40*52=93600, 55*40*52=114400
        assert second["salary_min"] == 93600
        assert second["salary_max"] == 114400
        assert "APIs and data pipelines" in second["description"]

    def test_deduplicates_by_job_id(self):
        results = parse_search_results(SEARCH_RESULTS_DUPLICATE_HTML)
        assert len(results) == 2
        assert len(set(r["job_id"] for r in results)) == 2

    def test_no_salary_returns_none(self):
        first = parse_search_results(SEARCH_RESULTS_NO_SALARY_HTML)[0]
        assert first["salary_min"] is None
        assert first["salary_max"] is None

    def test_graph_and_single_structures(self):
        graph = parse_search_results(SEARCH_RESULTS_GRAPH_HTML)
        assert len(graph) == 1
        assert graph[0]["company"] == "CloudOps Ltd"

        single = parse_search_results(SEARCH_RESULTS_SINGLE_HTML)
        assert len(single) == 1
        assert single[0]["salary_min"] == 90000

    def test_html_in_description_stripped(self):
        desc = parse_search_results(SEARCH_RESULTS_HTML_DESC)[0]["description"]
        assert "<div>" not in desc
        assert "React" in desc

    def test_empty_results(self):
        assert parse_search_results(SEARCH_RESULTS_NO_JSONLD_HTML) == []


# ---------------------------------------------------------------------------
# TalentSource class
# ---------------------------------------------------------------------------


class TestTalentSource:
    def test_name(self):
        assert TalentSource().name == "talent"

    async def test_empty_keywords_returns_empty(self):
        assert await TalentSource().scrape(SearchQuery(keywords=[])) == []

    async def test_scrape_returns_complete_opportunities(self):
        """Full scrape: verifies count, types, all fields, and hourly conversion."""
        p = _mock_talent_scrape([_response(SEARCH_RESULTS_HTML), _response(SEARCH_RESULTS_NO_JSONLD_HTML)])
        try:
            results = await TalentSource().scrape(
                SearchQuery(keywords=["python", "developer"], location="Montreal")
            )
        finally:
            p.stop()

        assert len(results) == 2
        assert all(isinstance(r, Opportunity) for r in results)
        assert all(r.source == "talent" for r in results)

        first = results[0]
        assert first.company == "TechCorp Inc"
        assert first.title == "Senior Python Developer"
        assert first.description
        assert "talent.com" in first.source_url
        assert "Montreal" in first.location
        assert first.salary_min == 95000
        assert first.salary_max == 130000
        assert first.posted_date.year == 2026
        assert first.raw_data["job_id"] == "job-abc-123"

        # Hourly conversion
        second = results[1]
        assert second.salary_min == 93600
        assert second.salary_max == 114400

    async def test_respects_max_results(self):
        p = _mock_talent_scrape([_response(SEARCH_RESULTS_HTML)])
        try:
            results = await TalentSource().scrape(SearchQuery(keywords=["dev"], max_results=1))
        finally:
            p.stop()
        assert len(results) == 1

    async def test_pagination(self):
        p = _mock_talent_scrape([
            _response(SEARCH_RESULTS_HTML),
            _response(SEARCH_RESULTS_PAGE2_HTML),
            _response(SEARCH_RESULTS_NO_JSONLD_HTML),
        ])
        try:
            results = await TalentSource().scrape(SearchQuery(keywords=["dev"], max_results=10))
        finally:
            p.stop()
        assert len(results) == 3
        assert "Page 2 Job" in [r.title for r in results]

    async def test_pagination_stops_on_http_error(self):
        p = _mock_talent_scrape([_response(SEARCH_RESULTS_HTML), httpx.HTTPError("Connection failed")])
        try:
            results = await TalentSource().scrape(SearchQuery(keywords=["dev"], max_results=50))
        finally:
            p.stop()
        assert len(results) == 2

    async def test_no_salary_results_in_none(self):
        p = _mock_talent_scrape([_response(SEARCH_RESULTS_NO_SALARY_HTML), _response(SEARCH_RESULTS_NO_JSONLD_HTML)])
        try:
            results = await TalentSource().scrape(SearchQuery(keywords=["dev"]))
        finally:
            p.stop()
        assert results[0].salary_min is None

    async def test_scrape_and_persist_deduplicates(self, tmp_path: Path):
        from datetime import datetime as dt
        db_conn = init_db(tmp_path / "test.db")
        resps = [_response(SEARCH_RESULTS_HTML), _response(SEARCH_RESULTS_NO_JSONLD_HTML)]

        p = _mock_talent_scrape(resps)
        try:
            saved_first = await TalentSource().scrape_and_persist(SearchQuery(keywords=["dev"]), db_conn)
        finally:
            p.stop()

        # Create applications so dedup sees them as active
        for opp in saved_first:
            save_application(db_conn, Application(
                opportunity_id=opp.id, status=ApplicationStatus.SCORED,
                created_at=dt.now(), updated_at=dt.now(),
            ))

        p = _mock_talent_scrape(resps)
        try:
            saved_second = await TalentSource().scrape_and_persist(SearchQuery(keywords=["dev"]), db_conn)
        finally:
            p.stop()

        assert len(saved_first) == 2
        assert len(saved_second) == 0
        db_conn.close()


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------


class TestSourceRegistration:
    def test_talent_in_available_sources(self):
        from emplaiyed.sources import get_available_sources
        sources = get_available_sources()
        assert "talent" in sources
        assert isinstance(sources["talent"], TalentSource)


# ---------------------------------------------------------------------------
# Integration test (requires network)
# ---------------------------------------------------------------------------

_has_network = os.environ.get("EMPLAIYED_TEST_NETWORK", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(not _has_network, reason="Set EMPLAIYED_TEST_NETWORK=1")
class TestTalentIntegration:
    async def test_real_search(self):
        results = await TalentSource().scrape(
            SearchQuery(keywords=["software developer"], location="montreal", max_results=5)
        )
        assert len(results) > 0
        for opp in results:
            assert opp.source == "talent"
            assert opp.company
            assert opp.title
