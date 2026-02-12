from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from emplaiyed.core.database import init_db, list_opportunities, save_opportunity
from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery


# ---------------------------------------------------------------------------
# Mock scraper for testing
# ---------------------------------------------------------------------------


class MockSource(BaseSource):
    """A trivial source that returns pre-configured results."""

    def __init__(self, results: list[Opportunity] | None = None):
        self._results = results or []

    @property
    def name(self) -> str:
        return "mock"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        return list(self._results)


# ---------------------------------------------------------------------------
# SearchQuery tests
# ---------------------------------------------------------------------------


class TestSearchQuery:
    def test_defaults(self):
        q = SearchQuery()
        assert q.keywords == []
        assert q.location is None
        assert q.radius_km is None
        assert q.max_results == 50

    def test_custom_values(self):
        q = SearchQuery(
            keywords=["python", "senior"],
            location="Quebec City",
            radius_km=25,
            max_results=10,
        )
        assert q.keywords == ["python", "senior"]
        assert q.location == "Quebec City"
        assert q.radius_km == 25
        assert q.max_results == 10


# ---------------------------------------------------------------------------
# scrape_and_persist tests
# ---------------------------------------------------------------------------


def _make_opp(company: str, title: str, source: str = "mock") -> Opportunity:
    return Opportunity(
        source=source,
        company=company,
        title=title,
        description="desc",
        scraped_at=datetime.now(),
    )


@pytest.fixture()
def db_conn(tmp_path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "test.db")
    yield conn
    conn.close()


class TestScrapeAndPersist:
    async def test_saves_new_opportunities(self, db_conn):
        opps = [_make_opp("Acme", "Dev"), _make_opp("Globex", "PM")]
        source = MockSource(opps)

        saved = await source.scrape_and_persist(SearchQuery(), db_conn)

        assert len(saved) == 2
        assert len(list_opportunities(db_conn)) == 2

    async def test_deduplicates_by_company_title_source(self, db_conn):
        # Pre-save one opportunity
        existing = _make_opp("Acme", "Dev")
        save_opportunity(db_conn, existing)

        # Scrape returns the same (company, title, source) plus a new one
        opps = [_make_opp("Acme", "Dev"), _make_opp("Globex", "PM")]
        source = MockSource(opps)

        saved = await source.scrape_and_persist(SearchQuery(), db_conn)

        # Only the new one should be saved
        assert len(saved) == 1
        assert saved[0].company == "Globex"
        # Total in DB: the pre-existing + the new one
        assert len(list_opportunities(db_conn)) == 2

    async def test_dedup_is_case_insensitive(self, db_conn):
        save_opportunity(db_conn, _make_opp("acme", "dev"))

        opps = [_make_opp("ACME", "DEV")]
        source = MockSource(opps)

        saved = await source.scrape_and_persist(SearchQuery(), db_conn)
        assert len(saved) == 0

    async def test_dedup_within_same_batch(self, db_conn):
        """Two identical items in the same scrape batch -- only the first should be saved."""
        opps = [_make_opp("Acme", "Dev"), _make_opp("Acme", "Dev")]
        source = MockSource(opps)

        saved = await source.scrape_and_persist(SearchQuery(), db_conn)
        assert len(saved) == 1

    async def test_empty_scrape_results(self, db_conn):
        source = MockSource([])
        saved = await source.scrape_and_persist(SearchQuery(), db_conn)
        assert saved == []
