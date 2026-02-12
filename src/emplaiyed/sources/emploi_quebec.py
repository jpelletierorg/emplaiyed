from __future__ import annotations

from emplaiyed.core.models import Opportunity
from emplaiyed.sources.base import BaseSource, SearchQuery


class EmploiQuebecSource(BaseSource):
    """Scraper for Quebec government job board (quebec.ca/emploi).

    The Quebec Emploi platform (formerly Placement en ligne) does not expose a
    public API.  A full implementation would need to use browser automation
    (e.g. Playwright) to interact with the search form at
    https://www.quebecemploi.gouv.qc.ca/plateforme-emploi/ and parse the
    resulting HTML.

    This is currently a stub. Call ``scrape()`` to see the status.
    """

    @property
    def name(self) -> str:
        return "emploi_quebec"

    async def scrape(self, query: SearchQuery) -> list[Opportunity]:
        """Not yet implemented.

        Raises:
            NotImplementedError: Always -- this source requires browser
                automation that has not been built yet.
        """
        raise NotImplementedError(
            "EmploiQuebecSource is not yet implemented. "
            "The Quebec Emploi platform (quebecemploi.gouv.qc.ca) does not "
            "expose a public API; scraping it requires browser automation "
            "(e.g. Playwright) which has not been built yet."
        )
