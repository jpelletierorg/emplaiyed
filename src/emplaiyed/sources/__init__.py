from __future__ import annotations

from emplaiyed.sources.base import BaseSource, SearchQuery
from emplaiyed.sources.emploi_quebec import EmploiQuebecSource
from emplaiyed.sources.jobbank import JobBankSource
from emplaiyed.sources.manual import ManualSource

__all__ = [
    "BaseSource",
    "SearchQuery",
    "ManualSource",
    "EmploiQuebecSource",
    "JobBankSource",
    "get_available_sources",
]


def get_available_sources() -> dict[str, BaseSource]:
    """Return all registered sources, keyed by their name."""
    sources: list[BaseSource] = [
        ManualSource(),
        EmploiQuebecSource(),
        JobBankSource(),
    ]
    return {s.name: s for s in sources}
