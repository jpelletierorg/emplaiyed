"""Job Bank Canada scraper — fetches jobs from jobbank.gc.ca.

Scrapes the Government of Canada's Job Bank search results and individual
posting pages to produce fully populated Opportunity objects.

The site is server-rendered HTML (PrimeFaces/JSF), so no headless browser
is needed — httpx + BeautifulSoup is sufficient.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.jobbank.gc.ca"
_SEARCH_PATH = "/jobsearch/jobsearch"

# Province codes used by Job Bank
PROVINCE_CODES: dict[str, str] = {
    "alberta": "AB",
    "british columbia": "BC",
    "manitoba": "MB",
    "new brunswick": "NB",
    "newfoundland": "NL",
    "northwest territories": "NT",
    "nova scotia": "NS",
    "nunavut": "NU",
    "ontario": "ON",
    "prince edward island": "PE",
    "quebec": "QC",
    "québec": "QC",
    "saskatchewan": "SK",
    "yukon": "YT",
}

# City-to-province mapping for common Canadian cities.
# Job Bank only supports province-level filtering (fprov=), so when the user
# provides a city name we map it to the province.
CITY_TO_PROVINCE: dict[str, str] = {
    "calgary": "AB",
    "edmonton": "AB",
    "red deer": "AB",
    "lethbridge": "AB",
    "vancouver": "BC",
    "victoria": "BC",
    "burnaby": "BC",
    "surrey": "BC",
    "kelowna": "BC",
    "winnipeg": "MB",
    "brandon": "MB",
    "fredericton": "NB",
    "moncton": "NB",
    "saint john": "NB",
    "st. john's": "NL",
    "halifax": "NS",
    "sydney": "NS",
    "yellowknife": "NT",
    "iqaluit": "NU",
    "toronto": "ON",
    "ottawa": "ON",
    "mississauga": "ON",
    "brampton": "ON",
    "hamilton": "ON",
    "london": "ON",
    "kitchener": "ON",
    "waterloo": "ON",
    "windsor": "ON",
    "kingston": "ON",
    "thunder bay": "ON",
    "charlottetown": "PE",
    "montreal": "QC",
    "montréal": "QC",
    "quebec city": "QC",
    "laval": "QC",
    "gatineau": "QC",
    "longueuil": "QC",
    "sherbrooke": "QC",
    "trois-rivières": "QC",
    "trois-rivieres": "QC",
    "saguenay": "QC",
    "lévis": "QC",
    "levis": "QC",
    "saskatoon": "SK",
    "regina": "SK",
    "whitehorse": "YT",
}


def _build_search_url(query: SearchQuery) -> str:
    """Build the Job Bank search URL from a SearchQuery."""
    params: dict[str, str] = {
        "searchstring": " ".join(query.keywords),
        "sort": "M",  # sort by best match
    }

    if query.location:
        # Split "Montreal, QC" into parts and try each one
        parts = [p.strip().lower() for p in query.location.split(",") if p.strip()]
        matched = False

        for part in parts:
            # Try province name / code
            for name, code in PROVINCE_CODES.items():
                if name == part or code.lower() == part:
                    params["fprov"] = code
                    matched = True
                    break
            if matched:
                break

            # Try city-to-province mapping
            province = CITY_TO_PROVINCE.get(part)
            if province:
                params["fprov"] = province
                matched = True
                logger.debug("Mapped city %r to province %s", part, province)
                break

        if not matched:
            logger.warning(
                "Could not map location %r to a province — searching all of Canada",
                query.location,
            )

    url = f"{_BASE_URL}{_SEARCH_PATH}?{urlencode(params)}"
    logger.debug("Search URL: %s", url)
    return url


def _parse_job_id(href: str) -> str | None:
    """Extract the numeric job ID from a posting href.

    Example href: /jobsearch/jobposting/48919846;jsessionid=ABC?source=searchresults
    Returns: "48919846"
    """
    match = re.search(r"/jobposting/(\d+)", href)
    return match.group(1) if match else None


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Try to extract salary_min and salary_max from a salary string.

    Handles formats like:
    - "$65.52 to $80.00 hourly"
    - "$80,000 to $100,000 annually"
    - "$45.00 hourly"
    """
    numbers = re.findall(r"\$[\d,]+(?:\.\d+)?", text)
    if not numbers:
        return None, None

    def _parse_num(s: str) -> int:
        return int(float(s.replace("$", "").replace(",", "")))

    is_hourly = "hour" in text.lower()

    vals = [_parse_num(n) for n in numbers]
    if is_hourly:
        # Convert hourly to annual estimate (40h/week * 52 weeks)
        vals = [int(v * 40 * 52) for v in vals]

    if len(vals) == 1:
        return vals[0], vals[0]
    return vals[0], vals[-1]


def _parse_date(text: str) -> datetime | None:
    """Parse a date string like 'February 09, 2026'."""
    text = text.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


def parse_search_results(html: str) -> list[dict]:
    """Parse the search results page and return a list of partial job dicts.

    Each dict contains: job_id, title, company, location, salary_text,
    posted_date, url.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    # Job listings are <a> tags with href containing /jobsearch/jobposting/
    for link in soup.find_all("a", href=re.compile(r"/jobsearch/jobposting/\d+")):
        href = link.get("href", "")
        job_id = _parse_job_id(href)
        if not job_id:
            continue

        # Extract text content from the listing
        h3 = link.find("h3")
        title_text = h3.get_text(strip=True) if h3 else ""

        # The <ul> inside the <a> contains metadata items
        items: list[str] = []
        ul = link.find("ul")
        if ul:
            items = [li.get_text(separator=" ", strip=True) for li in ul.find_all("li")]

        company = ""
        location = ""
        salary_text = ""
        posted_date = ""

        for item in items:
            if item.startswith("Location"):
                location = re.sub(r"^Location:?\s*", "", item).strip()
                location = re.sub(r"\s+", " ", location)
            elif item.startswith("Salary") or "$" in item:
                salary_text = re.sub(r"^Salary:?\s*", "", item).strip()
                salary_text = re.sub(r"\s+", " ", salary_text)
            elif _parse_date(item):
                posted_date = item.strip()
            elif "Job number" not in item and "job number" not in item.lower():
                # Likely the company name
                if not company:
                    company = item.strip()

        # Clean up the title — it often has "New" prefix and source name
        title_clean = re.sub(r"^New\s+", "", title_text)
        # Remove source prefix like "Talent.com " or "Indeed "
        title_clean = re.sub(
            r"^(Talent\.com|Indeed|CareerBeacon|LinkedIn|Glassdoor|Monster)\s+",
            "",
            title_clean,
            flags=re.IGNORECASE,
        )

        # Build the clean URL (without jsessionid)
        clean_url = f"{_BASE_URL}/jobsearch/jobposting/{job_id}"

        results.append(
            {
                "job_id": job_id,
                "title": title_clean.strip() or "Unknown Title",
                "company": company or "Unknown Company",
                "location": location,
                "salary_text": salary_text,
                "posted_date": posted_date,
                "url": clean_url,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Individual posting parsing
# ---------------------------------------------------------------------------


def parse_job_posting(html: str) -> dict:
    """Parse an individual job posting page for the full description.

    Returns a dict with: description, title, company, location, salary_text.
    These can be used to enrich/override the search result data.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    # Try to get title from <h1>
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    # Try to find company name — often in <strong> near employer info
    company = ""
    for strong in soup.find_all("strong"):
        text = strong.get_text(strip=True)
        if text and "employer" not in text.lower() and ":" not in text:
            # Skip labels like "Job Title:", "Responsibilities:", etc.
            if len(text) < 100 and not any(
                kw in text.lower()
                for kw in [
                    "job title",
                    "responsibilities",
                    "skills",
                    "requirements",
                    "qualifications",
                    "education",
                    "experience",
                    "benefits",
                ]
            ):
                company = text
                break

    # Get the full page text as the description
    description = soup.get_text(separator="\n", strip=True)

    # Try to find location
    location = ""
    for li in soup.find_all("li"):
        text = li.get_text(separator=" ", strip=True)
        if "," in text and any(
            prov in text for prov in ["QC", "ON", "BC", "AB", "MB", "SK", "NB", "NS", "NL", "PE", "NT", "NU", "YT"]
        ):
            location = re.sub(r"^Location:?\s*", "", text).strip()
            location = re.sub(r"\s+", " ", location)
            break

    # Try to find salary
    salary_text = ""
    for td in soup.find_all("td"):
        text = td.get_text(strip=True)
        if "$" in text and ("hour" in text.lower() or "year" in text.lower()):
            salary_text = text
            break

    return {
        "title": title,
        "company": company,
        "location": location,
        "salary_text": salary_text,
        "description": description,
    }


# ---------------------------------------------------------------------------
# Source implementation
# ---------------------------------------------------------------------------


class JobBankSource(BaseSource):
    """Job Bank Canada (jobbank.gc.ca) source."""

    @property
    def name(self) -> str:
        return "jobbank"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Scrape Job Bank search results and fetch full descriptions.

        1. Fetch the search results page
        2. Parse listing summaries (title, company, location, salary)
        3. Fetch each individual posting page for the full description
        4. Return fully populated Opportunity objects
        """
        if not query.keywords:
            logger.debug("No keywords provided, returning empty results")
            return []

        search_url = _build_search_url(query)
        logger.debug("Starting scrape: keywords=%s, location=%s", query.keywords, query.location)

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
            # Step 1: Fetch search results
            response = await client.get(search_url)
            response.raise_for_status()
            listings = parse_search_results(response.text)
            logger.debug("Found %d listings on search page", len(listings))

            # Respect max_results
            listings = listings[: query.max_results]

            # Step 2: Fetch each posting for full details
            opportunities: list[Opportunity] = []
            for listing in listings:
                try:
                    logger.debug("Fetching posting %s: %s", listing["job_id"], listing["url"])
                    posting_resp = await client.get(listing["url"])
                    posting_resp.raise_for_status()
                    posting_data = parse_job_posting(posting_resp.text)
                except httpx.HTTPError:
                    # If we can't fetch the detail page, use what we have
                    posting_data = {"description": "", "title": "", "company": "", "location": "", "salary_text": ""}

                # Merge: prefer detail page data where available, fall back
                # to search listing data
                title = posting_data["title"] or listing["title"]
                company = posting_data["company"] or listing["company"]
                location = posting_data["location"] or listing["location"]
                salary_text = posting_data["salary_text"] or listing["salary_text"]
                description = posting_data["description"] or f"{title} at {company}"

                salary_min, salary_max = _parse_salary(salary_text)
                posted = _parse_date(listing["posted_date"]).date() if _parse_date(listing["posted_date"]) else None

                opp = Opportunity(
                    source="jobbank",
                    source_url=listing["url"],
                    company=company,
                    title=title,
                    description=description,
                    location=location,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    posted_date=posted,
                    scraped_at=datetime.now(),
                    raw_data={
                        "job_id": listing["job_id"],
                        "salary_text": salary_text,
                    },
                )
                opportunities.append(opp)

        return opportunities
