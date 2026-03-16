"""Talent.com scraper -- fetches jobs from talent.com.

Scrapes the Talent.com job aggregator search results to produce
Opportunity objects.

Talent.com is a Canadian-founded (Montreal) job aggregator at ca.talent.com.
The site uses Next.js/React with client-side rendering, but embeds job data
in JSON-LD schema markup (<script type="application/ld+json">) in the
initial HTML response. We extract structured data from those tags,
avoiding the need for a headless browser.

URL format:
    https://www.talent.com/jobs?k={keywords}&l={location}&r={radius}

The JSON-LD contains schema.org JobPosting objects with fields like:
    title, hiringOrganization.name, jobLocation, description,
    datePosted, baseSalary, url, identifier, etc.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.talent.com"
_SEARCH_PATH = "/jobs"


def _build_search_url(query: SearchQuery, page: int = 0) -> str:
    """Build the Talent.com search URL from a SearchQuery.

    Talent.com uses query parameters:
        k — keyword string
        l — location / city name
        r — radius in km (default 50)
        p — page number (0-indexed)
    """
    params: dict[str, str] = {}

    if query.keywords:
        params["k"] = " ".join(query.keywords)

    if query.location:
        params["l"] = query.location

    if query.radius_km:
        params["r"] = str(query.radius_km)

    if page > 0:
        params["p"] = str(page)

    url = (
        f"{_BASE_URL}{_SEARCH_PATH}?{urlencode(params)}"
        if params
        else f"{_BASE_URL}{_SEARCH_PATH}"
    )
    logger.debug("Search URL: %s", url)
    return url


def _parse_salary(salary_data: dict | str | None) -> tuple[int | None, int | None]:
    """Extract salary_min and salary_max from JSON-LD baseSalary.

    JSON-LD baseSalary can be:
    - A dict with "value" containing "minValue"/"maxValue" or just "value"
    - A string like "$80,000 - $100,000"
    - None
    """
    if salary_data is None:
        return None, None

    if isinstance(salary_data, str):
        # Try to extract numbers from a salary string
        numbers = re.findall(r"[\d,]+(?:\.\d+)?", salary_data.replace("$", ""))
        if not numbers:
            return None, None
        vals = [int(float(n.replace(",", ""))) for n in numbers]
        if len(vals) == 1:
            return vals[0], vals[0]
        return vals[0], vals[-1]

    if isinstance(salary_data, dict):
        value = salary_data.get("value", {})
        unit_text = salary_data.get("unitText", "").upper()

        if isinstance(value, dict):
            min_val = value.get("minValue")
            max_val = value.get("maxValue")
            raw_value = value.get("value")
        elif isinstance(value, (int, float)):
            min_val = value
            max_val = value
            raw_value = None
        else:
            # Try parsing value as string
            return _parse_salary(str(value))

        def _to_int(v: int | float | str | None) -> int | None:
            if v is None:
                return None
            try:
                return int(float(str(v).replace(",", "")))
            except (ValueError, TypeError):
                return None

        sal_min = _to_int(min_val) or _to_int(raw_value)
        sal_max = _to_int(max_val) or _to_int(raw_value)

        # Convert hourly to annual (40h/week * 52 weeks)
        if unit_text in ("HOUR", "HOURLY") and sal_min is not None:
            sal_min = int(sal_min * 40 * 52)
            if sal_max is not None:
                sal_max = int(sal_max * 40 * 52)

        return sal_min, sal_max

    return None, None


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string from JSON-LD datePosted field.

    Common formats: "2026-02-10", "2026-02-10T15:30:00Z"
    """
    if not date_str:
        return None
    date_str = date_str.strip()

    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _extract_location(job: dict) -> str:
    """Extract location string from a JSON-LD JobPosting.

    jobLocation can be:
    - A dict with address.addressLocality, address.addressRegion, etc.
    - A list of such dicts
    - A string
    """
    loc = job.get("jobLocation")
    if not loc:
        return ""

    if isinstance(loc, str):
        return loc

    if isinstance(loc, list):
        loc = loc[0] if loc else {}

    if isinstance(loc, dict):
        address = loc.get("address", {})
        if isinstance(address, str):
            return address
        if isinstance(address, dict):
            parts = []
            city = address.get("addressLocality", "")
            region = address.get("addressRegion", "")
            country = address.get("addressCountry", "")
            if city:
                parts.append(city)
            if region:
                parts.append(region)
            if country and country not in parts:
                parts.append(country)
            return ", ".join(parts)

    return ""


def _extract_company(job: dict) -> str:
    """Extract company name from JSON-LD hiringOrganization."""
    org = job.get("hiringOrganization")
    if not org:
        return "Unknown Company"

    if isinstance(org, str):
        return org

    if isinstance(org, dict):
        return org.get("name", "Unknown Company")

    return "Unknown Company"


def _extract_hiring_org(job: dict) -> dict | None:
    """Return the full hiringOrganization dict for contact extraction.

    Preserves contactPoint, applicationContact, and other nested
    fields that ``_extract_company`` discards.
    """
    org = job.get("hiringOrganization")
    if isinstance(org, dict):
        return org
    return None


def _extract_job_id(job: dict) -> str | None:
    """Extract a unique job identifier from JSON-LD.

    Tries: identifier.value, identifier, or falls back to the URL.
    """
    identifier = job.get("identifier")
    if isinstance(identifier, dict):
        return str(identifier.get("value", ""))
    if isinstance(identifier, (str, int)):
        return str(identifier)

    # Fall back to URL-based ID
    url = job.get("url", "")
    if url:
        # Extract a path-based ID
        match = re.search(r"/job/([^/?#]+)", url)
        if match:
            return match.group(1)

    return None


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


def extract_jsonld_jobs(html: str) -> list[dict]:
    """Extract JobPosting objects from JSON-LD script tags in the HTML.

    Returns a list of dicts, each representing a schema.org JobPosting.
    Handles both single objects and @graph arrays.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []

    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string
        if not text:
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Failed to parse JSON-LD block")
            continue

        # Handle different JSON-LD structures
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    jobs.append(item)
        elif isinstance(data, dict):
            if data.get("@type") == "JobPosting":
                jobs.append(data)
            elif "@graph" in data:
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        jobs.append(item)

    return jobs


def parse_search_results(html: str) -> list[dict]:
    """Parse Talent.com search results page.

    Extracts job data from JSON-LD markup embedded in the HTML.

    Returns a list of dicts, each with: job_id, title, company, location,
    description, salary_min, salary_max, posted_date, url.
    """
    jsonld_jobs = extract_jsonld_jobs(html)
    results: list[dict] = []
    seen_ids: set[str] = set()

    for job in jsonld_jobs:
        job_id = _extract_job_id(job)
        if not job_id:
            # Generate a fallback ID from title + company
            title = job.get("title", "")
            company = _extract_company(job)
            job_id = f"{title}-{company}".lower().replace(" ", "-")[:64]

        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title = job.get("title", "Unknown Title")
        company = _extract_company(job)
        location = _extract_location(job)
        description = job.get("description", "")
        url = job.get("url", "")
        date_posted = job.get("datePosted")
        salary_data = job.get("baseSalary")

        salary_min, salary_max = _parse_salary(salary_data)
        posted_date = _parse_date(date_posted)

        # Clean up description (may contain HTML)
        if description and "<" in description:
            desc_soup = BeautifulSoup(description, "html.parser")
            description = desc_soup.get_text(separator="\n", strip=True)

        results.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "posted_date": posted_date,
                "url": url,
                "hiring_org": _extract_hiring_org(job),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Source implementation
# ---------------------------------------------------------------------------


class TalentSource(BaseSource):
    """Talent.com (talent.com) Canadian job aggregator source."""

    @property
    def name(self) -> str:
        return "talent"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Scrape Talent.com search results.

        1. Build the search URL from keywords and location
        2. Fetch the search results page
        3. Extract job data from JSON-LD markup
        4. Return Opportunity objects
        """
        if not query.keywords:
            logger.debug("No keywords provided, returning empty results")
            return []

        logger.debug(
            "Starting scrape: keywords=%s, location=%s",
            query.keywords,
            query.location,
        )

        all_listings: list[dict] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8",
            },
        ) as client:
            # Fetch first page
            search_url = _build_search_url(query)
            response = await client.get(search_url)
            response.raise_for_status()
            listings = parse_search_results(response.text)
            logger.debug("Found %d listings on page 0", len(listings))

            for listing in listings:
                if listing["job_id"] not in seen_ids:
                    seen_ids.add(listing["job_id"])
                    all_listings.append(listing)

            # Paginate if needed and we haven't hit max_results yet
            page = 1
            while len(all_listings) < query.max_results and len(listings) > 0:
                search_url = _build_search_url(query, page=page)
                try:
                    response = await client.get(search_url)
                    response.raise_for_status()
                except httpx.HTTPError:
                    logger.debug("Failed to fetch page %d, stopping pagination", page)
                    break

                listings = parse_search_results(response.text)
                if not listings:
                    break

                new_count = 0
                for listing in listings:
                    if listing["job_id"] not in seen_ids:
                        seen_ids.add(listing["job_id"])
                        all_listings.append(listing)
                        new_count += 1

                if new_count == 0:
                    # No new results, stop paginating
                    break

                page += 1
                logger.debug("Found %d new listings on page %d", new_count, page - 1)

        # Respect max_results
        all_listings = all_listings[: query.max_results]

        opportunities: list[Opportunity] = []
        for listing in all_listings:
            posted = listing["posted_date"].date() if listing["posted_date"] else None

            opp = Opportunity(
                source="talent",
                source_url=listing["url"] or None,
                company=listing["company"],
                title=listing["title"],
                description=listing["description"]
                or f"{listing['title']} at {listing['company']}",
                location=listing["location"] or None,
                salary_min=listing["salary_min"],
                salary_max=listing["salary_max"],
                posted_date=posted,
                scraped_at=datetime.now(),
                raw_data={
                    "job_id": listing["job_id"],
                    "hiring_org": listing.get("hiring_org"),
                },
            )
            opportunities.append(opp)

        return opportunities
