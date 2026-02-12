from __future__ import annotations

import pytest

from emplaiyed.sources.base import SearchQuery
from emplaiyed.sources.emploi_quebec import EmploiQuebecSource


class TestEmploiQuebecSource:
    def test_name(self):
        src = EmploiQuebecSource()
        assert src.name == "emploi_quebec"

    async def test_scrape_raises_not_implemented(self):
        src = EmploiQuebecSource()
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            await src.scrape(SearchQuery(keywords=["python"]))
