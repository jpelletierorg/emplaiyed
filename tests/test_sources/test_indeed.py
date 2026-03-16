"""Tests for emplaiyed.sources.indeed -- Indeed Canada via python-jobspy."""

from __future__ import annotations

import math
import os
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from emplaiyed.core.database import init_db, save_application
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
from emplaiyed.sources.base import SearchQuery
from emplaiyed.sources.indeed import (
    IndeedSource,
    _dataframe_to_opportunities,
    _normalise_salary,
    _safe_int,
    _safe_str,
)


# ---------------------------------------------------------------------------
# Sample DataFrame fixtures
# ---------------------------------------------------------------------------


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame matching the jobspy output column structure."""
    columns = [
        "id",
        "site",
        "job_url",
        "job_url_direct",
        "title",
        "company",
        "location",
        "date_posted",
        "job_type",
        "salary_source",
        "interval",
        "min_amount",
        "max_amount",
        "currency",
        "is_remote",
        "job_level",
        "job_function",
        "listing_type",
        "emails",
        "description",
        "company_industry",
        "company_url",
        "company_logo",
        "company_url_direct",
        "company_addresses",
        "company_num_employees",
        "company_revenue",
        "company_description",
        "skills",
        "experience_range",
        "company_rating",
        "company_reviews_count",
        "vacancy_count",
        "work_from_home_type",
    ]
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df


SAMPLE_ROW_ANNUAL = {
    "id": "indeed-abc123",
    "site": "indeed",
    "job_url": "https://ca.indeed.com/viewjob?jk=abc123",
    "job_url_direct": "https://company.com/careers/abc123",
    "title": "Senior Python Developer",
    "company": "TechCorp Montreal",
    "location": "Montreal, QC",
    "date_posted": date(2026, 2, 15),
    "job_type": "fulltime",
    "salary_source": "direct_data",
    "interval": "yearly",
    "min_amount": 95000.0,
    "max_amount": 130000.0,
    "currency": "CAD",
    "is_remote": False,
    "job_level": "senior",
    "description": "We are looking for a **Senior Python Developer** to join our team.",
    "company_industry": "Technology",
    "company_url": "https://techcorp.ca",
    "emails": "hr@techcorp.ca",
}

SAMPLE_ROW_HOURLY = {
    "id": "indeed-def456",
    "site": "indeed",
    "job_url": "https://ca.indeed.com/viewjob?jk=def456",
    "title": "Cloud Engineer",
    "company": "CloudOps Inc",
    "location": "Laval, QC",
    "date_posted": date(2026, 2, 12),
    "interval": "hourly",
    "min_amount": 45.0,
    "max_amount": 55.0,
    "currency": "CAD",
    "is_remote": True,
    "description": "Join our cloud team. AWS, GCP, Terraform.",
}

SAMPLE_ROW_NO_SALARY = {
    "id": "indeed-ghi789",
    "site": "indeed",
    "job_url": "https://ca.indeed.com/viewjob?jk=ghi789",
    "title": "AI Research Intern",
    "company": "ML Labs",
    "location": "Montreal, QC",
    "date_posted": None,
    "description": "Exciting internship opportunity in AI research.",
}

SAMPLE_ROW_MINIMAL = {
    "title": "Junior Developer",
    "company": "StartupCo",
    "job_url": "https://ca.indeed.com/viewjob?jk=min001",
    "description": "Entry-level position.",
}

SAMPLE_DF = _make_df([SAMPLE_ROW_ANNUAL, SAMPLE_ROW_HOURLY, SAMPLE_ROW_NO_SALARY])


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSafeInt:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (95000.0, 95000),
            (45, 45),
            ("100", 100),
            (None, None),
            (float("nan"), None),
            (float("inf"), None),
            ("abc", None),
        ],
        ids=["float", "int", "string", "none", "nan", "inf", "invalid"],
    )
    def test_conversion(self, value, expected):
        assert _safe_int(value) == expected


class TestSafeStr:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Montreal, QC", "Montreal, QC"),
            (None, None),
            (float("nan"), None),
            ("  ", None),
            ("", None),
            (42, "42"),
        ],
        ids=["normal", "none", "nan", "whitespace", "empty", "number"],
    )
    def test_conversion(self, value, expected):
        assert _safe_str(value) == expected


class TestNormaliseSalary:
    @pytest.mark.parametrize(
        "min_amt,max_amt,interval,expected",
        [
            (95000.0, 130000.0, "yearly", (95000, 130000)),
            (45.0, 55.0, "hourly", (93600, 114400)),
            (5000.0, 7000.0, "monthly", (60000, 84000)),
            (2000.0, 2500.0, "weekly", (104000, 130000)),
            (350.0, 450.0, "daily", (91000, 117000)),
            (None, None, "yearly", (None, None)),
            (None, None, None, (None, None)),
            (80000.0, None, "yearly", (80000, None)),
            (None, 120000.0, "yearly", (None, 120000)),
            (float("nan"), float("nan"), "yearly", (None, None)),
        ],
        ids=[
            "annual",
            "hourly",
            "monthly",
            "weekly",
            "daily",
            "none-none",
            "none-interval",
            "min-only",
            "max-only",
            "nan",
        ],
    )
    def test_normalisation(self, min_amt, max_amt, interval, expected):
        assert _normalise_salary(min_amt, max_amt, interval) == expected


# ---------------------------------------------------------------------------
# DataFrame to Opportunities conversion
# ---------------------------------------------------------------------------


class TestDataframeToOpportunities:
    def test_converts_all_rows(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        assert len(opps) == 3
        assert all(isinstance(o, Opportunity) for o in opps)

    def test_annual_salary_preserved(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        first = opps[0]
        assert first.salary_min == 95000
        assert first.salary_max == 130000

    def test_hourly_converted_to_annual(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        second = opps[1]
        # 45 * 40 * 52 = 93600, 55 * 40 * 52 = 114400
        assert second.salary_min == 93600
        assert second.salary_max == 114400

    def test_no_salary_returns_none(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        third = opps[2]
        assert third.salary_min is None
        assert third.salary_max is None

    def test_source_is_indeed(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        assert all(o.source == "indeed" for o in opps)

    def test_fields_mapped_correctly(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        first = opps[0]
        assert first.title == "Senior Python Developer"
        assert first.company == "TechCorp Montreal"
        assert first.location == "Montreal, QC"
        assert first.source_url == "https://ca.indeed.com/viewjob?jk=abc123"
        assert "Senior Python Developer" in first.description
        assert first.posted_date == date(2026, 2, 15)

    def test_raw_data_includes_extras(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        first = opps[0]
        assert first.raw_data is not None
        assert first.raw_data["id"] == "indeed-abc123"
        assert first.raw_data["job_url_direct"] == "https://company.com/careers/abc123"
        assert first.raw_data["company_industry"] == "Technology"
        assert first.raw_data["emails"] == "hr@techcorp.ca"

    def test_is_remote_in_raw_data(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        second = opps[1]
        assert second.raw_data is not None
        assert second.raw_data["is_remote"] is True

    def test_null_posted_date_handled(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=10)
        third = opps[2]
        assert third.posted_date is None

    def test_respects_max_results(self):
        opps = _dataframe_to_opportunities(SAMPLE_DF, max_results=1)
        assert len(opps) == 1

    def test_empty_dataframe(self):
        opps = _dataframe_to_opportunities(pd.DataFrame(), max_results=10)
        assert opps == []

    def test_minimal_row(self):
        df = _make_df([SAMPLE_ROW_MINIMAL])
        opps = _dataframe_to_opportunities(df, max_results=10)
        assert len(opps) == 1
        opp = opps[0]
        assert opp.title == "Junior Developer"
        assert opp.company == "StartupCo"
        assert opp.salary_min is None
        assert opp.salary_max is None


# ---------------------------------------------------------------------------
# IndeedSource class
# ---------------------------------------------------------------------------


class TestIndeedSource:
    def test_name(self):
        assert IndeedSource().name == "indeed"

    async def test_empty_keywords_returns_empty(self):
        results = await IndeedSource().scrape(SearchQuery(keywords=[]))
        assert results == []

    async def test_scrape_returns_opportunities(self):
        """Full scrape with mocked jobspy -- verifies mapping and async wrapper."""
        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            return_value=SAMPLE_DF,
        ):
            results = await IndeedSource().scrape(
                SearchQuery(
                    keywords=["python", "developer"],
                    location="Montreal",
                    max_results=10,
                )
            )

        assert len(results) == 3
        assert all(isinstance(r, Opportunity) for r in results)
        assert all(r.source == "indeed" for r in results)

        first = results[0]
        assert first.company == "TechCorp Montreal"
        assert first.title == "Senior Python Developer"
        assert first.salary_min == 95000
        assert first.salary_max == 130000
        assert first.location == "Montreal, QC"

        # Hourly conversion
        second = results[1]
        assert second.salary_min == 93600
        assert second.salary_max == 114400

    async def test_scrape_respects_max_results(self):
        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            return_value=SAMPLE_DF,
        ):
            results = await IndeedSource().scrape(
                SearchQuery(keywords=["dev"], max_results=1)
            )
        assert len(results) == 1

    async def test_scrape_handles_empty_dataframe(self):
        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            return_value=pd.DataFrame(),
        ):
            results = await IndeedSource().scrape(
                SearchQuery(keywords=["dev"], max_results=10)
            )
        assert results == []

    async def test_scrape_handles_exception_gracefully(self):
        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            side_effect=RuntimeError("Network error"),
        ):
            results = await IndeedSource().scrape(
                SearchQuery(keywords=["dev"], max_results=10)
            )
        assert results == []

    async def test_scrape_joins_keywords(self):
        """Verify keywords are joined into a single search term."""
        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            return_value=pd.DataFrame(),
        ) as mock_scrape:
            await IndeedSource().scrape(
                SearchQuery(
                    keywords=["python", "AI", "engineer"],
                    location="Montreal",
                )
            )
            mock_scrape.assert_called_once_with(
                search_term="python AI engineer",
                location="Montreal",
                results_wanted=50,
            )

    async def test_scrape_and_persist_deduplicates(self, tmp_path: Path):
        db_conn = init_db(tmp_path / "test.db")

        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            return_value=SAMPLE_DF,
        ):
            saved_first = await IndeedSource().scrape_and_persist(
                SearchQuery(keywords=["dev"]), db_conn
            )

        # Create applications so dedup sees them as existing
        for opp in saved_first:
            save_application(
                db_conn,
                Application(
                    opportunity_id=opp.id,
                    status=ApplicationStatus.SCORED,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                ),
            )

        with patch(
            "emplaiyed.sources.indeed._run_jobspy_scrape",
            return_value=SAMPLE_DF,
        ):
            saved_second = await IndeedSource().scrape_and_persist(
                SearchQuery(keywords=["dev"]), db_conn
            )

        assert len(saved_first) == 3
        assert len(saved_second) == 0
        db_conn.close()


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------


class TestSourceRegistration:
    def test_indeed_in_available_sources(self):
        from emplaiyed.sources import get_available_sources

        sources = get_available_sources()
        assert "indeed" in sources
        assert isinstance(sources["indeed"], IndeedSource)


# ---------------------------------------------------------------------------
# Integration test (requires network)
# ---------------------------------------------------------------------------

_has_network = os.environ.get("EMPLAIYED_TEST_NETWORK", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.mark.skipif(not _has_network, reason="Set EMPLAIYED_TEST_NETWORK=1")
class TestIndeedIntegration:
    async def test_real_search(self):
        results = await IndeedSource().scrape(
            SearchQuery(
                keywords=["software developer"],
                location="Montreal",
                max_results=5,
            )
        )
        assert len(results) > 0
        for opp in results:
            assert opp.source == "indeed"
            assert opp.company
            assert opp.title
