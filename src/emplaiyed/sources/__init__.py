from __future__ import annotations

from emplaiyed.sources.base import BaseSource, SearchQuery
from emplaiyed.sources.guichet_emplois import GuichetEmploisSource
from emplaiyed.sources.indeed import IndeedSource
from emplaiyed.sources.jobbank import JobBankSource
from emplaiyed.sources.jobillico import JobillicoSource
from emplaiyed.sources.manual import ManualSource
from emplaiyed.sources.talent import TalentSource

__all__ = [
    "BaseSource",
    "SearchQuery",
    "ManualSource",
    "JobBankSource",
    "JobillicoSource",
    "TalentSource",
    "GuichetEmploisSource",
    "IndeedSource",
    "get_available_sources",
]


def get_available_sources() -> dict[str, BaseSource]:
    """Return all registered sources, keyed by their name."""
    sources: list[BaseSource] = [
        ManualSource(),
        JobBankSource(),
        JobillicoSource(),
        TalentSource(),
        GuichetEmploisSource(),
        IndeedSource(),
    ]
    return {s.name: s for s in sources}
