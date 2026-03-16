"""Jobillico scraper — fetches jobs from jobillico.com.

Scrapes the Jobillico Quebec job board search results to produce
Opportunity objects.

The search results page is server-rendered HTML (with Vue.js enhancing
it client-side), so httpx + BeautifulSoup is sufficient — no headless
browser needed.

URL format:
    https://www.jobillico.com/search-jobs?skwd={keywords}&sjdpl={location}

Job offer links come in two flavours:
    /en/job-offer/{company-slug}/{title-slug}/{job_id}  (native listings)
    /see-partner-offer/{partner_id}                     (aggregated listings)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup, Tag

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.jobillico.com"
_SEARCH_PATH = "/search-jobs"


def _build_search_url(query: SearchQuery) -> str:
    """Build the Jobillico search URL from a SearchQuery.

    Jobillico uses query parameters:
        skwd  — keyword string
        sjdpl — location / city name
    """
    params: dict[str, str] = {}

    if query.keywords:
        params["skwd"] = " ".join(query.keywords)

    if query.location:
        params["sjdpl"] = query.location

    # Build URL manually to avoid double-encoding
    qs = "&".join(f"{k}={v.replace(' ', '+')}" for k, v in params.items())
    url = f"{_BASE_URL}{_SEARCH_PATH}?{qs}" if qs else f"{_BASE_URL}{_SEARCH_PATH}"
    logger.debug("Search URL: %s", url)
    return url


def _parse_days_ago(text: str) -> datetime | None:
    """Parse relative time strings like '5 day(s)' or '30+ day(s)'.

    Returns an approximate datetime, or None if unparseable.
    """
    text = text.strip()
    match = re.search(r"(\d+)\+?\s*day", text, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        return datetime.now() - timedelta(days=days)
    return None


def _extract_job_id_from_href(href: str) -> str | None:
    """Extract the numeric job ID from a Jobillico job offer href.

    Native listings:   /en/job-offer/company/title/16720230?...  -> "16720230"
    Partner listings:  /see-partner-offer/21989278?...           -> "p-21989278"
    """
    # Native job offer
    match = re.search(r"/en/job-offer/[^/]+/[^/]+/(\d+)", href)
    if match:
        return match.group(1)

    # Partner offer
    match = re.search(r"/see-partner-offer/(\d+)", href)
    if match:
        return f"p-{match.group(1)}"

    return None


def _clean_job_url(href: str) -> str:
    """Strip tracking query params from a job offer URL.

    Keeps only the path portion (before '?') and prepends the base URL
    if the href is relative.
    """
    clean = href.split("?")[0]
    if clean.startswith("/"):
        return f"{_BASE_URL}{clean}"
    if clean.startswith("http"):
        return clean
    return f"{_BASE_URL}/{clean}"


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


def parse_search_results(html: str) -> list[dict]:
    """Parse the Jobillico search results page.

    Returns a list of dicts, each with: job_id, title, company, location,
    description, work_type, posted_date, url, is_partner.

    The HTML structure (per listing):
        <article class="... card card--clickable ...">
          <div class="card__content">
            <header class="relative">
              <h2 class="h3 ..."><a href="/en/job-offer/...">{title}</a></h2>
              <h3 class="h4">
                <a class="link companyLink">{company}</a>
                — or —
                <span class="link companyLink">{company}</span>
              </h3>
            </header>
            <p class="xs word-break">{description snippet}</p>
            <ul class="list list--has-no-bullets">
              <li>  icon--information--position  → location   </li>
              <li>  icon--information--clock      → work type  </li>
              <li>  icon--information--calendar   → posted ago </li>
            </ul>
          </div>
        </article>
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen_ids: set[str] = set()

    # The job listings container
    container = soup.find(id="jobOffersList")
    if not container:
        logger.debug("No #jobOffersList container found")
        return results

    for article in container.find_all("article", class_="card"):
        # --- Title & URL ---
        h2 = article.find("h2")
        if not h2:
            continue
        link = h2.find("a", href=True)
        if not link:
            continue

        href = link.get("href", "")
        job_id = _extract_job_id_from_href(href)
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title = link.get_text(strip=True)
        url = _clean_job_url(href)
        is_partner = "has-tag-partner" in " ".join(article.get("class", []))

        # --- Company ---
        company = ""
        h3 = article.find("h3")
        if h3:
            company_el = h3.find(class_="companyLink")
            if company_el:
                company = company_el.get_text(strip=True)

        # --- Description snippet ---
        desc_p = article.find("p", class_="xs")
        description = desc_p.get_text(strip=True) if desc_p else ""

        # --- Metadata from the <ul> list ---
        location = ""
        work_type = ""
        posted_date: datetime | None = None

        for li in article.find_all("li", class_="list__item"):
            if li.find(class_="icon--information--position"):
                p = li.find("p")
                if p:
                    location = p.get_text(strip=True)
            elif li.find(class_="icon--information--clock"):
                p = li.find("p")
                if p:
                    work_type = p.get_text(strip=True)
            elif li.find(class_="icon--information--calendar"):
                time_el = li.find("time")
                if time_el:
                    posted_date = _parse_days_ago(time_el.get_text(strip=True))

        results.append(
            {
                "job_id": job_id,
                "title": title or "Unknown Title",
                "company": company or "Unknown Company",
                "location": location,
                "description": description,
                "work_type": work_type,
                "posted_date": posted_date,
                "url": url,
                "is_partner": is_partner,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Source implementation
# ---------------------------------------------------------------------------


class JobillicoSource(BaseSource):
    """Jobillico (jobillico.com) Quebec job board source."""

    @property
    def name(self) -> str:
        return "jobillico"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Scrape Jobillico search results.

        1. Build the search URL from keywords and location
        2. Fetch the search results page
        3. Parse listing summaries (title, company, location, description)
        4. Return Opportunity objects
        """
        if not query.keywords:
            logger.debug("No keywords provided, returning empty results")
            return []

        search_url = _build_search_url(query)
        logger.debug(
            "Starting scrape: keywords=%s, location=%s",
            query.keywords,
            query.location,
        )

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
            response = await client.get(search_url)
            response.raise_for_status()
            listings = parse_search_results(response.text)
            logger.debug("Found %d listings on search page", len(listings))

        # Respect max_results
        listings = listings[: query.max_results]

        opportunities: list[Opportunity] = []
        for listing in listings:
            posted = listing["posted_date"].date() if listing["posted_date"] else None

            opp = Opportunity(
                source="jobillico",
                source_url=listing["url"],
                company=listing["company"],
                title=listing["title"],
                description=listing["description"] or f"{listing['title']} at {listing['company']}",
                location=listing["location"] or None,
                salary_min=None,
                salary_max=None,
                posted_date=posted,
                scraped_at=datetime.now(),
                raw_data={
                    "job_id": listing["job_id"],
                    "work_type": listing["work_type"],
                    "is_partner": listing["is_partner"],
                },
            )
            opportunities.append(opp)

        return opportunities
