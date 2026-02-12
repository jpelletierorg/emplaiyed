from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from emplaiyed.core.database import list_opportunities, save_opportunity
from emplaiyed.core.models import Opportunity

logger = logging.getLogger(__name__)


@dataclass
class SearchQuery:
    """Parameters for a job search."""

    keywords: list[str] = field(default_factory=list)
    location: str | None = None
    radius_km: int | None = None
    max_results: int = 50


class BaseSource(ABC):
    """Base class for all job sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Source identifier (e.g. 'indeed', 'linkedin')."""

    @abstractmethod
    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Scrape job listings matching the query."""

    async def scrape_and_persist(
        self, query: SearchQuery, db_conn: sqlite3.Connection
    ) -> list[Opportunity]:
        """Scrape and save to database. Handles deduplication.

        Deduplication: skip opportunities where an existing row already has
        the same (company, title, source) combination.
        """
        opportunities = await self.scrape(query)
        logger.debug("Scraped %d opportunities from %s", len(opportunities), self.name)
        existing = list_opportunities(db_conn, source=self.name)

        # Build a set of (company_lower, title_lower, source) for fast lookup
        existing_keys: set[tuple[str, str, str]] = {
            (o.company.lower(), o.title.lower(), o.source.lower())
            for o in existing
        }

        saved: list[Opportunity] = []
        skipped = 0
        for opp in opportunities:
            key = (opp.company.lower(), opp.title.lower(), opp.source.lower())
            if key not in existing_keys:
                save_opportunity(db_conn, opp)
                existing_keys.add(key)
                saved.append(opp)
            else:
                skipped += 1
                logger.debug("Skipping duplicate: %s at %s", opp.title, opp.company)

        logger.debug("Saved %d new, skipped %d duplicates", len(saved), skipped)
        return saved
