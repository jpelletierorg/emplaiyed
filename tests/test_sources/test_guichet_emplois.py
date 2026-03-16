"""Tests for emplaiyed.sources.guichet_emplois — Guichet-Emplois (French Job Bank) scraper."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from emplaiyed.core.database import init_db, list_opportunities, save_application
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
from emplaiyed.sources.base import SearchQuery
from emplaiyed.sources.guichet_emplois import (
    GuichetEmploisSource,
    _build_search_url,
    _parse_french_date,
    _parse_job_id,
    _parse_salary,
    parse_search_results,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SEARCH_RESULTS_HTML = """
<html>
<body>
<form id="ajaxupdateform">
  <article class="action-buttons" id="article-48933047">
    <a class="resultJobItem"
       href="/rechercheemplois/offredemploi/48933047;jsessionid=ABC123.jobsearch75?source=searchresults">
      <h3 class="title">
        <span class="flag">
          <span class="new">Nouveau</span>
          <span class="telework">Sur place</span>
          <span class="appmethod">Candidature directe</span>
          <span class="postedonJB">
            Publiée sur le Guichet-Emplois
            <span class="description">
              <span aria-hidden="true" class="fa fa-info-circle"></span>
              Cette offre d'emploi a été publiée directement par l'employeur.
            </span>
          </span>
        </span>
        <span class="job-source job-source-icon-16">
          <span class="wb-inv">Guichet-Emplois</span>
        </span>
        <span class="noctitle">développeur/développeuse logiciel</span>
      </h3>
      <ul class="list-unstyled">
        <li class="date">12 février 2026</li>
        <li class="business">Technologies ABC Inc.</li>
        <li class="location">
          <span aria-hidden="true" class="fas fa-map-marker-alt"></span>
          <span class="wb-inv">Emplacement</span>
          Montréal (QC)
        </li>
        <li class="salary">
          <span aria-hidden="true" class="fa fa-dollar"></span>
          Salaire :
          85 000,00 $ par année
        </li>
        <li class="source">
          <span class="job-source job-source-icon-16">
            <span class="wb-inv">Guichet-Emplois</span>
          </span>
          <span class="wb-inv">Numéro de l'offre :</span>
          <span aria-hidden="true" class="fa fa-hashtag"></span>
          3505275
        </li>
      </ul>
    </a>
  </article>

  <article class="action-buttons" id="article-48953349">
    <a class="resultJobItem"
       href="/rechercheemplois/offredemploi/48953349;jsessionid=ABC123.jobsearch75?source=searchresults">
      <h3 class="title">
        <span class="flag">
          <span class="new">Nouveau</span>
        </span>
        <span class="job-source job-source-icon-3">
          <span class="wb-inv">Québec emploi</span>
        </span>
        <span class="noctitle">analyste en informatique</span>
      </h3>
      <ul class="list-unstyled">
        <li class="date">16 février 2026</li>
        <li class="business">Gouvernement du Québec</li>
        <li class="location">
          <span aria-hidden="true" class="fas fa-map-marker-alt"></span>
          <span class="wb-inv">Emplacement</span>
          Québec (QC)
        </li>
        <li class="salary">
          <span aria-hidden="true" class="fa fa-dollar"></span>
          Salaire :
          65 000,00 $ à 90 000,00 $ par année
        </li>
        <li class="source">
          <span class="job-source job-source-icon-3">
            <span class="wb-inv">Québec emploi</span>
          </span>
          <span class="wb-inv">Numéro de l'offre :</span>
          <span aria-hidden="true" class="fa fa-hashtag"></span>
          519825
        </li>
      </ul>
    </a>
  </article>

  <article class="action-buttons" id="article-48562057">
    <a class="resultJobItem"
       href="/rechercheemplois/offredemploi/48562057;jsessionid=ABC123.jobsearch75?source=searchresults">
      <h3 class="title">
        <span class="flag">
          <span class="telework">Télétravail</span>
        </span>
        <span class="job-source job-source-icon-16">
          <span class="wb-inv">Guichet-Emplois</span>
        </span>
        <span class="noctitle">technicien/technicienne en soutien informatique</span>
      </h3>
      <ul class="list-unstyled">
        <li class="date">5 janvier 2026</li>
        <li class="business">Services TI Québec</li>
        <li class="location">
          <span aria-hidden="true" class="fas fa-map-marker-alt"></span>
          <span class="wb-inv">Emplacement</span>
          Sherbrooke (QC)
        </li>
        <li class="salary">
          <span aria-hidden="true" class="fa fa-dollar"></span>
          Salaire :
          22,50 $ de l'heure
        </li>
        <li class="source">
          <span class="job-source job-source-icon-16">
            <span class="wb-inv">Guichet-Emplois</span>
          </span>
          <span class="wb-inv">Numéro de l'offre :</span>
          <span aria-hidden="true" class="fa fa-hashtag"></span>
          3480012
        </li>
      </ul>
    </a>
  </article>
</form>
</body>
</html>
"""

SEARCH_RESULTS_EMPTY_HTML = """
<html>
<body>
<form id="ajaxupdateform">
  <div class="alert alert-warning">
    <p>Aucun résultat trouvé.</p>
  </div>
</form>
</body>
</html>
"""

SEARCH_RESULTS_NO_ARTICLES_HTML = """
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
def mock_guichet_http(response_html: str):
    """Context manager that patches httpx.AsyncClient to return the given HTML.

    Yields the mock client so callers can inspect calls if needed.
    """
    response = httpx.Response(
        status_code=200,
        text=response_html,
        request=httpx.Request(
            "GET", "https://www.guichetemplois.gc.ca/jobsearch/jobsearch"
        ),
    )
    with patch("emplaiyed.sources.guichet_emplois.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        yield mock_client


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestParseJobId:
    @pytest.mark.parametrize(
        "href, expected",
        [
            ("/rechercheemplois/offredemploi/48933047;jsessionid=ABC?source=searchresults", "48933047"),
            ("/rechercheemplois/offredemploi/48953349", "48953349"),
            ("/some/other/path", None),
            ("", None),
        ],
        ids=["standard_href", "clean_href", "no_match", "empty_string"],
    )
    def test_parse_job_id(self, href: str, expected: str | None) -> None:
        assert _parse_job_id(href) == expected


class TestParseFrenchDate:
    @pytest.mark.parametrize(
        "text, expected_month, expected_day, expected_year",
        [
            ("12 février 2026", 2, 12, 2026),
            ("5 janvier 2026", 1, 5, 2026),
            ("25 décembre 2025", 12, 25, 2025),
            ("1 mars 2026", 3, 1, 2026),
            ("10 avril 2026", 4, 10, 2026),
            ("20 mai 2026", 5, 20, 2026),
            ("15 juin 2026", 6, 15, 2026),
            ("7 juillet 2026", 7, 7, 2026),
            ("15 aout 2026", 8, 15, 2026),
            ("3 septembre 2026", 9, 3, 2026),
            ("31 octobre 2026", 10, 31, 2026),
            ("11 novembre 2026", 11, 11, 2026),
            ("16 Février 2026", 2, 16, 2026),  # case insensitive
        ],
        ids=[
            "février", "janvier", "décembre", "mars", "avril", "mai",
            "juin", "juillet", "août_no_accent", "septembre", "octobre",
            "novembre", "case_insensitive",
        ],
    )
    def test_french_months(
        self, text: str, expected_month: int, expected_day: int, expected_year: int
    ) -> None:
        result = _parse_french_date(text)
        assert result is not None
        assert result.year == expected_year
        assert result.month == expected_month
        assert result.day == expected_day

    @pytest.mark.parametrize(
        "text, expected_month, expected_day, expected_year",
        [
            ("February 12, 2026", 2, 12, 2026),
            ("2026-02-12", 2, 12, 2026),
        ],
        ids=["english_fallback", "iso_format"],
    )
    def test_fallback_formats(
        self, text: str, expected_month: int, expected_day: int, expected_year: int
    ) -> None:
        result = _parse_french_date(text)
        assert result is not None
        assert result.year == expected_year
        assert result.month == expected_month
        assert result.day == expected_day

    @pytest.mark.parametrize(
        "text",
        ["not a date", ""],
        ids=["invalid_string", "empty_string"],
    )
    def test_returns_none_for_invalid(self, text: str) -> None:
        assert _parse_french_date(text) is None


class TestParseSalary:
    @pytest.mark.parametrize(
        "text, expected_min, expected_max",
        [
            ("85 000,00 $ par année", 85000, 85000),
            ("75 000 $ par année", 75000, 75000),
            ("65 000,00 $ à 90 000,00 $ par année", 65000, 90000),
            ("22,50 $ de l'heure", 46800, 46800),       # 22.50 * 40 * 52
            ("20,00 $ à 25,00 $ de l'heure", 41600, 52000),  # 20*40*52 / 25*40*52
        ],
        ids=[
            "annual_single", "annual_integer", "annual_range",
            "hourly_single", "hourly_range",
        ],
    )
    def test_salary_parsing(self, text: str, expected_min: int, expected_max: int) -> None:
        salary_min, salary_max = _parse_salary(text)
        assert salary_min == expected_min
        assert salary_max == expected_max

    @pytest.mark.parametrize(
        "text",
        ["", "Salaire compétitif"],
        ids=["empty", "no_dollar_sign"],
    )
    def test_returns_none_for_unparseable(self, text: str) -> None:
        assert _parse_salary(text) == (None, None)


class TestBuildSearchUrl:
    @pytest.mark.parametrize(
        "query, expected_fragments, absent_fragments",
        [
            (
                SearchQuery(keywords=["python", "developer"]),
                ["guichetemplois.gc.ca/jobsearch/jobsearch", "searchstring=python+developer", "sort=M"],
                [],
            ),
            (
                SearchQuery(keywords=[]),
                ["searchstring=", "sort=M"],
                [],
            ),
            (
                SearchQuery(keywords=["developer"], location="Quebec"),
                ["fprov=QC"],
                [],
            ),
            (
                SearchQuery(keywords=["developer"], location="Montreal"),
                ["fprov=QC"],
                [],
            ),
            (
                SearchQuery(keywords=["developer"], location="QC"),
                ["fprov=QC"],
                [],
            ),
            (
                SearchQuery(keywords=["developer"], location="Montreal, QC"),
                ["fprov=QC"],
                [],
            ),
            (
                SearchQuery(keywords=["developer"], location="Timbuktu"),
                [],
                ["fprov"],
            ),
        ],
        ids=[
            "basic_keywords", "no_keywords", "province_name",
            "city_name", "province_code", "city_and_province",
            "unknown_location",
        ],
    )
    def test_build_search_url(
        self,
        query: SearchQuery,
        expected_fragments: list[str],
        absent_fragments: list[str],
    ) -> None:
        url = _build_search_url(query)
        for frag in expected_fragments:
            assert frag in url
        for frag in absent_fragments:
            assert frag not in url


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


class TestParseSearchResults:
    def test_all_listings_parsed_with_correct_fields(self) -> None:
        """Parse all three listings and verify every field in one pass."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        assert len(results) == 3

        # --- First listing: annual salary, new, Sur place ---
        first = results[0]
        assert first["job_id"] == "48933047"
        assert first["title"] == "développeur/développeuse logiciel"
        assert first["company"] == "Technologies ABC Inc."
        assert "Montréal" in first["location"]
        assert "QC" in first["location"]
        assert first["salary_text"] == "85 000,00 $ par année"
        assert first["salary_min"] == 85000
        assert first["salary_max"] == 85000
        assert first["is_new"] is True
        assert first["work_mode"] == "Sur place"
        assert first["url"] == "https://www.guichetemplois.gc.ca/rechercheemplois/offredemploi/48933047"
        assert first["posted_date"] is not None
        assert first["posted_date"].month == 2
        assert first["posted_date"].day == 12

        # --- Second listing: salary range, new, no work_mode ---
        second = results[1]
        assert second["job_id"] == "48953349"
        assert second["title"] == "analyste en informatique"
        assert second["company"] == "Gouvernement du Québec"
        assert second["salary_min"] == 65000
        assert second["salary_max"] == 90000
        assert second["posted_date"] is not None
        assert second["posted_date"].day == 16

        # --- Third listing: hourly salary, not new, Télétravail ---
        third = results[2]
        assert third["job_id"] == "48562057"
        assert third["title"] == "technicien/technicienne en soutien informatique"
        assert third["company"] == "Services TI Québec"
        assert "Sherbrooke" in third["location"]
        assert third["salary_min"] == 46800  # 22.50 * 40 * 52
        assert third["salary_max"] == 46800
        assert third["is_new"] is False
        assert third["work_mode"] == "Télétravail"
        assert third["posted_date"] is not None
        assert third["posted_date"].month == 1

    def test_job_ids_are_unique(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_HTML)
        ids = [r["job_id"] for r in results]
        assert len(ids) == len(set(ids))

    def test_urls_are_clean(self) -> None:
        """URLs should not contain jsessionid or query parameters."""
        results = parse_search_results(SEARCH_RESULTS_HTML)
        for r in results:
            assert "jsessionid" not in r["url"]
            assert "?" not in r["url"]

    def test_empty_results(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_EMPTY_HTML)
        assert results == []

    def test_no_articles(self) -> None:
        results = parse_search_results(SEARCH_RESULTS_NO_ARTICLES_HTML)
        assert results == []

    def test_duplicate_job_ids_deduplicated(self) -> None:
        """If HTML contains duplicate articles, only keep the first."""
        html_with_dupe = """
        <html><body>
          <article class="action-buttons" id="article-12345">
            <a class="resultJobItem"
               href="/rechercheemplois/offredemploi/12345;jsessionid=X?source=sr">
              <h3 class="title">
                <span class="noctitle">Job A</span>
              </h3>
              <ul class="list-unstyled">
                <li class="business">Company A</li>
              </ul>
            </a>
          </article>
          <article class="action-buttons" id="article-12345">
            <a class="resultJobItem"
               href="/rechercheemplois/offredemploi/12345;jsessionid=Y?source=sr">
              <h3 class="title">
                <span class="noctitle">Job A Duplicate</span>
              </h3>
              <ul class="list-unstyled">
                <li class="business">Company A</li>
              </ul>
            </a>
          </article>
        </body></html>
        """
        results = parse_search_results(html_with_dupe)
        assert len(results) == 1
        assert results[0]["title"] == "Job A"


# ---------------------------------------------------------------------------
# GuichetEmploisSource class
# ---------------------------------------------------------------------------


class TestGuichetEmploisSource:
    def test_name(self) -> None:
        source = GuichetEmploisSource()
        assert source.name == "guichet_emplois"

    async def test_empty_keywords_returns_empty(self) -> None:
        source = GuichetEmploisSource()
        result = await source.scrape(SearchQuery(keywords=[]))
        assert result == []

    async def test_scrape_returns_opportunities_with_all_fields(self) -> None:
        """Full scrape flow: verify count, types, source tag, and all fields on each listing."""
        source = GuichetEmploisSource()

        with mock_guichet_http(SEARCH_RESULTS_HTML):
            results = await source.scrape(
                SearchQuery(keywords=["developer"], location="Montreal")
            )

        # --- Basic invariants ---
        assert len(results) == 3
        assert all(isinstance(r, Opportunity) for r in results)
        assert all(r.source == "guichet_emplois" for r in results)

        # --- First listing: all fields populated ---
        first = results[0]
        assert first.company == "Technologies ABC Inc."
        assert first.title == "développeur/développeuse logiciel"
        assert first.description  # not empty
        assert first.source_url
        assert "guichetemplois.gc.ca" in first.source_url
        assert first.location is not None
        assert "Montréal" in first.location
        assert first.salary_min == 85000
        assert first.salary_max == 85000
        assert first.posted_date is not None
        assert first.posted_date.month == 2
        assert first.scraped_at is not None
        assert first.raw_data is not None
        assert first.raw_data["job_id"] == "48933047"
        assert first.raw_data["is_new"] is True
        assert first.raw_data["work_mode"] == "Sur place"

        # --- Second listing: salary range ---
        second = results[1]
        assert second.salary_min == 65000
        assert second.salary_max == 90000

        # --- Third listing: hourly-to-annual conversion ---
        third = results[2]
        assert third.salary_min == 46800  # 22.50 * 40 * 52
        assert third.salary_max == 46800

    async def test_respects_max_results(self) -> None:
        """Only return up to max_results opportunities."""
        source = GuichetEmploisSource()

        with mock_guichet_http(SEARCH_RESULTS_HTML):
            results = await source.scrape(
                SearchQuery(keywords=["developer"], max_results=2)
            )

        assert len(results) == 2

    async def test_scrape_and_persist_deduplicates(self, tmp_path: Path) -> None:
        """scrape_and_persist should not save duplicates."""
        source = GuichetEmploisSource()
        db_conn = init_db(tmp_path / "test.db")

        with mock_guichet_http(SEARCH_RESULTS_HTML):
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

        # Run again -- same results should be deduped
        with mock_guichet_http(SEARCH_RESULTS_HTML):
            saved_second = await source.scrape_and_persist(
                SearchQuery(keywords=["developer"]), db_conn
            )

        assert len(saved_first) == 3
        assert len(saved_second) == 0  # all dupes
        assert len(list_opportunities(db_conn, source="guichet_emplois")) == 3

        db_conn.close()


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------


class TestSourceRegistration:
    def test_guichet_emplois_in_available_sources(self) -> None:
        from emplaiyed.sources import get_available_sources

        sources = get_available_sources()
        assert "guichet_emplois" in sources
        assert isinstance(sources["guichet_emplois"], GuichetEmploisSource)


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
class TestGuichetEmploisIntegration:
    """Integration tests that hit the real guichetemplois.gc.ca site.

    These are skipped by default. Run with:
        EMPLAIYED_TEST_NETWORK=1 uv run pytest tests/test_sources/test_guichet_emplois.py -k integration
    """

    async def test_real_search(self) -> None:
        source = GuichetEmploisSource()
        results = await source.scrape(
            SearchQuery(
                keywords=["developer"],
                location="Quebec",
                max_results=5,
            )
        )
        # We expect at least some results
        assert len(results) > 0
        for opp in results:
            assert opp.source == "guichet_emplois"
            assert opp.company
            assert opp.title
            assert opp.description
            assert opp.source_url
            assert "guichetemplois.gc.ca" in opp.source_url
