from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from emplaiyed.sources.manual import ManualSource


# ---------------------------------------------------------------------------
# create_from_text tests
# ---------------------------------------------------------------------------


class TestCreateFromText:
    def test_basic_fields(self):
        src = ManualSource()
        opp = src.create_from_text(
            text="We need a Python dev.",
            company="Acme Inc",
            title="Senior Python Developer",
        )

        assert opp.source == "manual"
        assert opp.company == "Acme Inc"
        assert opp.title == "Senior Python Developer"
        assert opp.description == "We need a Python dev."
        assert opp.source_url is None
        assert isinstance(opp.scraped_at, datetime)

    def test_with_url_and_location(self):
        src = ManualSource()
        opp = src.create_from_text(
            text="Job desc",
            company="Globex",
            title="PM",
            url="https://example.com/job/123",
            location="Quebec City",
        )

        assert opp.source_url == "https://example.com/job/123"
        assert opp.location == "Quebec City"

    def test_id_is_generated(self):
        src = ManualSource()
        opp1 = src.create_from_text(text="a", company="A", title="T")
        opp2 = src.create_from_text(text="b", company="B", title="T")
        assert opp1.id != opp2.id

    def test_optional_fields_default_to_none(self):
        src = ManualSource()
        opp = src.create_from_text(text="x", company="C", title="T")
        assert opp.salary_min is None
        assert opp.salary_max is None
        assert opp.posted_date is None
        assert opp.raw_data is None


# ---------------------------------------------------------------------------
# create_from_url tests (mocked HTTP)
# ---------------------------------------------------------------------------

FAKE_HTML = """
<html>
<head><title>Senior Developer at Acme</title></head>
<body>
  <h1>Senior Developer</h1>
  <p>We are looking for an experienced developer to join our team.</p>
  <script>var x = 1;</script>
  <style>.hidden { display: none; }</style>
</body>
</html>
"""


class TestCreateFromUrl:
    async def test_fetches_and_parses(self):
        src = ManualSource()

        mock_response = httpx.Response(
            status_code=200,
            text=FAKE_HTML,
            request=httpx.Request("GET", "https://example.com/job"),
        )

        with patch("emplaiyed.sources.manual.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            opp = await src.create_from_url(
                url="https://example.com/job",
                company="Acme",
                title="Senior Dev",
            )

        assert opp.source == "manual"
        assert opp.company == "Acme"
        assert opp.title == "Senior Dev"
        assert opp.source_url == "https://example.com/job"
        # Script/style content should be removed
        assert "var x = 1" not in opp.description
        assert ".hidden" not in opp.description
        # Actual content should be present
        assert "experienced developer" in opp.description

    async def test_extracts_title_from_html_if_not_provided(self):
        src = ManualSource()

        mock_response = httpx.Response(
            status_code=200,
            text=FAKE_HTML,
            request=httpx.Request("GET", "https://example.com/job"),
        )

        with patch("emplaiyed.sources.manual.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            opp = await src.create_from_url(url="https://example.com/job")

        assert opp.title == "Senior Developer at Acme"
        assert opp.company == "Unknown Company"

    async def test_fallback_title_when_no_html_title(self):
        src = ManualSource()
        html_no_title = "<html><body><p>Hello</p></body></html>"

        mock_response = httpx.Response(
            status_code=200,
            text=html_no_title,
            request=httpx.Request("GET", "https://example.com/job"),
        )

        with patch("emplaiyed.sources.manual.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            opp = await src.create_from_url(url="https://example.com/job")

        assert opp.title == "Unknown Title"


# ---------------------------------------------------------------------------
# scrape() returns empty
# ---------------------------------------------------------------------------


class TestManualScrape:
    async def test_scrape_returns_empty(self):
        """ManualSource.scrape() should return an empty list."""
        from emplaiyed.sources.base import SearchQuery

        src = ManualSource()
        result = await src.scrape(SearchQuery())
        assert result == []
