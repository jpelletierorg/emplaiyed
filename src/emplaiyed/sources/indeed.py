"""Indeed Canada source -- fetches jobs via the python-jobspy library.

Wraps the python-jobspy library to scrape Indeed Canada job listings
and produce Opportunity objects compatible with the emplaiyed pipeline.

python-jobspy handles the anti-bot evasion (TLS fingerprinting, etc.)
that makes direct Indeed scraping infeasible with plain httpx+BS4.

Since scrape_jobs() is synchronous and returns a pandas DataFrame,
we run it in a thread via asyncio.to_thread() to avoid blocking
the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime

import pandas as pd

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery

logger = logging.getLogger(__name__)

# Hours per year for hourly -> annual conversion (40h/week * 52 weeks)
_HOURS_PER_YEAR = 40 * 52

# Map of interval strings to annual multipliers.
# jobspy normalises the interval field to these string values.
_INTERVAL_TO_ANNUAL: dict[str, int] = {
    "hourly": _HOURS_PER_YEAR,
    "daily": 260,  # ~5 days/week * 52 weeks
    "weekly": 52,
    "monthly": 12,
    "yearly": 1,
}


def _safe_int(value: object) -> int | None:
    """Convert a value to int, returning None for NaN / None / non-numeric."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value: object) -> str | None:
    """Convert to str, treating NaN / None as None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    return s if s else None


def _normalise_salary(
    min_amount: object,
    max_amount: object,
    interval: object,
) -> tuple[int | None, int | None]:
    """Convert salary figures to annual integers.

    If the interval is not yearly the amounts are multiplied by the
    appropriate factor so the rest of the pipeline can compare salaries
    on a common basis.
    """
    sal_min = _safe_int(min_amount)
    sal_max = _safe_int(max_amount)

    if sal_min is None and sal_max is None:
        return None, None

    interval_str = _safe_str(interval)
    multiplier = _INTERVAL_TO_ANNUAL.get(interval_str or "yearly", 1)

    if sal_min is not None:
        sal_min = int(sal_min * multiplier)
    if sal_max is not None:
        sal_max = int(sal_max * multiplier)

    return sal_min, sal_max


def _run_jobspy_scrape(
    search_term: str,
    location: str | None,
    results_wanted: int,
) -> pd.DataFrame:
    """Run python-jobspy synchronously (called via asyncio.to_thread)."""
    from jobspy import scrape_jobs

    kwargs: dict = {
        "site_name": ["indeed"],
        "search_term": search_term,
        "country_indeed": "Canada",
        "results_wanted": results_wanted,
        "description_format": "markdown",
        "verbose": 0,
    }

    if location:
        kwargs["location"] = location

    return scrape_jobs(**kwargs)


def _dataframe_to_opportunities(
    df: pd.DataFrame, max_results: int
) -> list[Opportunity]:
    """Convert a jobspy DataFrame into a list of Opportunity models."""
    opportunities: list[Opportunity] = []

    for _, row in df.head(max_results).iterrows():
        title = _safe_str(row.get("title")) or "Unknown Title"
        company = _safe_str(row.get("company")) or "Unknown Company"
        description = _safe_str(row.get("description")) or f"{title} at {company}"
        location = _safe_str(row.get("location"))
        job_url = _safe_str(row.get("job_url"))

        sal_min, sal_max = _normalise_salary(
            row.get("min_amount"),
            row.get("max_amount"),
            row.get("interval"),
        )

        posted_date = row.get("date_posted")
        if pd.isna(posted_date):
            posted_date = None

        # Build raw_data with extra Indeed-specific fields
        raw_data: dict = {}
        for key in (
            "id",
            "job_url_direct",
            "job_type",
            "is_remote",
            "interval",
            "currency",
            "company_industry",
            "company_url",
            "company_addresses",
            "company_num_employees",
            "company_revenue",
            "job_level",
            "emails",
            "salary_source",
        ):
            val = row.get(key)
            if val is not None and not (isinstance(val, float) and math.isnan(val)):
                raw_data[key] = val

        opp = Opportunity(
            source="indeed",
            source_url=job_url,
            company=company,
            title=title,
            description=description,
            location=location,
            salary_min=sal_min,
            salary_max=sal_max,
            posted_date=posted_date,
            scraped_at=datetime.now(),
            raw_data=raw_data if raw_data else None,
        )
        opportunities.append(opp)

    return opportunities


class IndeedSource(BaseSource):
    """Indeed Canada job source via the python-jobspy library."""

    @property
    def name(self) -> str:
        return "indeed"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Scrape Indeed Canada listings.

        1. Build a search term from keywords
        2. Run python-jobspy in a background thread
        3. Convert the DataFrame to Opportunity objects
        """
        if not query.keywords:
            logger.debug("No keywords provided, returning empty results")
            return []

        search_term = " ".join(query.keywords)
        logger.debug(
            "Starting Indeed scrape: search_term=%s, location=%s, max_results=%d",
            search_term,
            query.location,
            query.max_results,
        )

        try:
            df = await asyncio.to_thread(
                _run_jobspy_scrape,
                search_term=search_term,
                location=query.location,
                results_wanted=query.max_results,
            )
        except Exception:
            logger.exception("Indeed scrape failed")
            return []

        if df.empty:
            logger.debug("Indeed returned no results")
            return []

        opportunities = _dataframe_to_opportunities(df, query.max_results)
        logger.debug("Indeed returned %d opportunities", len(opportunities))
        return opportunities
