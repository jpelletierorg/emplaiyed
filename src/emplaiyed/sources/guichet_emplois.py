"""Guichet-Emplois scraper — fetches jobs from guichetemplois.gc.ca.

Scrapes the Government of Canada's French-language Job Bank (Guichet-Emplois)
search results to produce Opportunity objects.

This is the French interface to the same government job system as jobbank.gc.ca,
but it surfaces different listings because many Quebec employers post exclusively
in French. A search for "developer" in QC yields ~25 results on Guichet-Emplois
vs ~2 on the English Job Bank.

The site is server-rendered HTML (PrimeFaces/JSF), so httpx + BeautifulSoup
is sufficient — no headless browser needed.

URL format:
    https://www.guichetemplois.gc.ca/jobsearch/jobsearch?searchstring={keywords}&fprov={province}&sort=M

Job posting links:
    /rechercheemplois/offredemploi/{job_id};jsessionid=...?source=searchresults

HTML structure per listing:
    <article class="action-buttons" id="article-{job_id}">
      <a class="resultJobItem" href="/rechercheemplois/offredemploi/{job_id};...">
        <h3 class="title">
          <span class="flag">
            <span class="new">Nouveau</span>
            <span class="telework">Sur place / Télétravail</span>
          </span>
          <span class="noctitle">{job title}</span>
        </h3>
        <ul class="list-unstyled">
          <li class="date">{posted date}</li>
          <li class="business">{company}</li>
          <li class="location">{city} ({province})</li>
          <li class="salary">Salaire : {amount}</li>
        </ul>
      </a>
    </article>
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.guichetemplois.gc.ca"
_SEARCH_PATH = "/jobsearch/jobsearch"

# Province codes used by Guichet-Emplois (same as Job Bank)
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

# City-to-province mapping for common Canadian cities
CITY_TO_PROVINCE: dict[str, str] = {
    "calgary": "AB",
    "edmonton": "AB",
    "vancouver": "BC",
    "victoria": "BC",
    "winnipeg": "MB",
    "fredericton": "NB",
    "moncton": "NB",
    "halifax": "NS",
    "toronto": "ON",
    "ottawa": "ON",
    "mississauga": "ON",
    "hamilton": "ON",
    "london": "ON",
    "kitchener": "ON",
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

# French month names for date parsing
_FRENCH_MONTHS: dict[str, int] = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}


def _build_search_url(query: SearchQuery) -> str:
    """Build the Guichet-Emplois search URL from a SearchQuery."""
    params: dict[str, str] = {
        "searchstring": " ".join(query.keywords),
        "sort": "M",  # sort by best match
    }

    if query.location:
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

    Example href: /rechercheemplois/offredemploi/48933047;jsessionid=ABC?source=searchresults
    Returns: "48933047"
    """
    match = re.search(r"/offredemploi/(\d+)", href)
    return match.group(1) if match else None


def _parse_french_date(text: str) -> datetime | None:
    """Parse a French date string like '16 février 2026'.

    Also handles English-format dates like 'February 16, 2026' as fallback.
    """
    text = text.strip().lower()

    # Try French format: "16 février 2026"
    match = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))
        month = _FRENCH_MONTHS.get(month_name)
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    # Fallback: English format
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Extract salary_min and salary_max from a French salary string.

    Handles formats like:
    - "22,00 $ de l'heure" (hourly)
    - "75 000,00 $ par année" (annual)
    - "65,52 $ à 80,00 $ de l'heure" (hourly range)
    - "80 000 $ à 100 000 $ par année" (annual range)
    """
    # Normalize: replace non-breaking spaces with regular spaces
    text = text.replace("\xa0", " ").strip()

    # Extract all dollar amounts (French format uses space as thousands separator
    # and comma as decimal separator)
    # Pattern matches: "22,00 $", "75 000,00 $", "80 000 $"
    amounts = re.findall(r"([\d\s]+(?:,\d+)?)\s*\$", text)
    if not amounts:
        return None, None

    def _parse_amount(s: str) -> float:
        """Parse a French-format number like '75 000,00' to float."""
        s = s.strip()
        s = s.replace(" ", "")  # Remove thousands separator
        s = s.replace(",", ".")  # Decimal comma -> decimal point
        return float(s)

    is_hourly = "heure" in text.lower() or "hour" in text.lower()

    vals = [_parse_amount(a) for a in amounts]
    if is_hourly:
        # Convert hourly to annual estimate (40h/week * 52 weeks)
        vals = [v * 40 * 52 for v in vals]

    int_vals = [int(v) for v in vals]

    if len(int_vals) == 1:
        return int_vals[0], int_vals[0]
    return int_vals[0], int_vals[-1]


# ---------------------------------------------------------------------------
# Search results parsing
# ---------------------------------------------------------------------------


def parse_search_results(html: str) -> list[dict]:
    """Parse the Guichet-Emplois search results page.

    Returns a list of dicts, each with: job_id, title, company, location,
    salary_text, salary_min, salary_max, posted_date, url, is_new, work_mode.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen_ids: set[str] = set()

    for article in soup.find_all("article"):
        # The main link containing all the listing data
        link = article.find("a", class_="resultJobItem")
        if not link:
            continue

        href = link.get("href", "")
        job_id = _parse_job_id(href)
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # --- Title ---
        title = ""
        noctitle = link.find("span", class_="noctitle")
        if noctitle:
            title = noctitle.get_text(strip=True)

        # --- Flags (new, telework) ---
        is_new = False
        work_mode = ""
        flag_span = link.find("span", class_="flag")
        if flag_span:
            new_span = flag_span.find("span", class_="new")
            if new_span:
                is_new = True
            telework_span = flag_span.find("span", class_="telework")
            if telework_span:
                work_mode = telework_span.get_text(strip=True)

        # --- Metadata from <ul> ---
        company = ""
        location = ""
        salary_text = ""
        posted_date: datetime | None = None

        ul = link.find("ul", class_="list-unstyled")
        if ul:
            # Company
            biz_li = ul.find("li", class_="business")
            if biz_li:
                company = biz_li.get_text(strip=True)

            # Location
            loc_li = ul.find("li", class_="location")
            if loc_li:
                # Remove screen-reader text
                for sr in loc_li.find_all("span", class_="wb-inv"):
                    sr.decompose()
                # Remove icon span
                for icon in loc_li.find_all("span", attrs={"aria-hidden": "true"}):
                    icon.decompose()
                location = loc_li.get_text(strip=True)

            # Salary
            salary_li = ul.find("li", class_="salary")
            if salary_li:
                # Remove screen-reader text and icons
                for sr in salary_li.find_all("span"):
                    sr.decompose()
                raw_salary = salary_li.get_text(strip=True)
                # Strip the "Salaire :" prefix
                salary_text = re.sub(r"^Salaire\s*:\s*", "", raw_salary).strip()

            # Date
            date_li = ul.find("li", class_="date")
            if date_li:
                posted_date = _parse_french_date(date_li.get_text(strip=True))

        # Build clean URL
        clean_url = f"{_BASE_URL}/rechercheemplois/offredemploi/{job_id}"

        # Parse salary
        salary_min, salary_max = _parse_salary(salary_text)

        results.append(
            {
                "job_id": job_id,
                "title": title or "Titre inconnu",
                "company": company or "Employeur inconnu",
                "location": location,
                "salary_text": salary_text,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "posted_date": posted_date,
                "url": clean_url,
                "is_new": is_new,
                "work_mode": work_mode,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Source implementation
# ---------------------------------------------------------------------------


class GuichetEmploisSource(BaseSource):
    """Guichet-Emplois (guichetemplois.gc.ca) French-language Job Bank source.

    This source scrapes the French interface of the Government of Canada's
    Job Bank. It surfaces different listings from the English Job Bank because
    many Quebec employers post exclusively in French.
    """

    @property
    def name(self) -> str:
        return "guichet_emplois"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Scrape Guichet-Emplois search results.

        1. Build the search URL from keywords and location
        2. Fetch the search results page
        3. Parse listing summaries (title, company, location, salary, date)
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
                "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8",
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
                source="guichet_emplois",
                source_url=listing["url"],
                company=listing["company"],
                title=listing["title"],
                description=f"{listing['title']} at {listing['company']}",
                location=listing["location"] or None,
                salary_min=listing["salary_min"],
                salary_max=listing["salary_max"],
                posted_date=posted,
                scraped_at=datetime.now(),
                raw_data={
                    "job_id": listing["job_id"],
                    "salary_text": listing["salary_text"],
                    "is_new": listing["is_new"],
                    "work_mode": listing["work_mode"],
                },
            )
            opportunities.append(opp)

        return opportunities
