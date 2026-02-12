from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery


class ManualSource(BaseSource):
    """Manual paste source -- user provides job description directly.

    This source is useful for:
    - Pasting a job posting URL or text
    - Testing the pipeline without needing any automated scraper
    """

    @property
    def name(self) -> str:
        return "manual"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Not applicable for manual source.

        Use ``create_from_text`` or ``create_from_url`` instead.
        """
        return []

    def create_from_text(
        self,
        text: str,
        company: str,
        title: str,
        url: str | None = None,
        location: str | None = None,
    ) -> Opportunity:
        """Create an Opportunity from user-provided text.

        Args:
            text: The full job description text.
            company: Company name.
            title: Job title.
            url: Optional source URL.
            location: Optional location string.

        Returns:
            A fully populated Opportunity instance.
        """
        return Opportunity(
            source="manual",
            source_url=url,
            company=company,
            title=title,
            description=text,
            location=location,
            scraped_at=datetime.now(),
        )

    async def create_from_url(
        self,
        url: str,
        company: str | None = None,
        title: str | None = None,
    ) -> Opportunity:
        """Fetch a URL and create an Opportunity from its text content.

        Performs a simple HTTP GET, strips HTML tags, and uses the page text
        as the job description.  If *company* or *title* are not provided,
        the method attempts to extract them from the page (falling back to
        placeholder values).

        Args:
            url: The job posting URL.
            company: Company name (optional, extracted from page if missing).
            title: Job title (optional, extracted from page title if missing).

        Returns:
            A fully populated Opportunity instance.
        """
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script and style elements
        for tag in soup(["script", "style"]):
            tag.decompose()

        page_text = soup.get_text(separator="\n", strip=True)

        # Try to get a title from the <title> tag if not provided
        if title is None:
            page_title = soup.title.string if soup.title and soup.title.string else None
            title = _clean_text(page_title) if page_title else "Unknown Title"

        if company is None:
            company = "Unknown Company"

        return Opportunity(
            source="manual",
            source_url=url,
            company=company,
            title=title,
            description=page_text,
            scraped_at=datetime.now(),
        )


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip a string."""
    return re.sub(r"\s+", " ", text).strip()
