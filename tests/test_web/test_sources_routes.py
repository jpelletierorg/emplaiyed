"""Tests for sources web routes (Phase 3).

Validates source listing page, scan endpoint, and search endpoint.
Uses FastAPI TestClient with dependency overrides.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from emplaiyed.api.app import create_app
from emplaiyed.api.deps import get_db, get_profile, get_profile_path, get_data_dir
from emplaiyed.core.database import init_db
from emplaiyed.core.models import (
    Aspirations,
    Profile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


@pytest.fixture
def sample_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python", "FastAPI", "Docker"],
        aspirations=Aspirations(
            target_roles=["Backend Engineer"],
            geographic_preferences=["Montreal", "Remote"],
            work_arrangement=["hybrid"],
            salary_minimum=90000,
            salary_target=120000,
            urgency="within_3_months",
            statement="I want to build great software.",
        ),
    )


def _make_db_override(conn: sqlite3.Connection):
    """Create a generator dependency override for get_db."""

    def override():
        yield conn

    return override


@pytest.fixture
def client_with_profile(
    tmp_db: sqlite3.Connection,
    sample_profile: Profile,
    tmp_path: Path,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: sample_profile
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


@pytest.fixture
def client_no_profile(
    tmp_db: sqlite3.Connection,
    tmp_path: Path,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


# ---------------------------------------------------------------------------
# Sources page
# ---------------------------------------------------------------------------


class TestSourcesPage:
    def test_page_renders_with_profile(self, client_with_profile: TestClient) -> None:
        resp = client_with_profile.get("/sources")
        assert resp.status_code == 200
        assert "Sources" in resp.text
        assert "AI Search Agent" in resp.text
        assert "Manual Scan" in resp.text
        # Should show source names
        assert "jobbank" in resp.text

    def test_page_renders_without_profile(self, client_no_profile: TestClient) -> None:
        resp = client_no_profile.get("/sources")
        assert resp.status_code == 200
        # Should show a warning about needing a profile
        assert "profile" in resp.text.lower()

    def test_default_keywords_from_profile(
        self, client_with_profile: TestClient
    ) -> None:
        resp = client_with_profile.get("/sources")
        assert resp.status_code == 200
        # Keywords should be derived from profile
        assert "Backend Engineer" in resp.text
        assert "Python" in resp.text
        # Location should be derived
        assert "Montreal" in resp.text


# ---------------------------------------------------------------------------
# Sources list API
# ---------------------------------------------------------------------------


class TestSourcesListAPI:
    def test_list_sources(self, client_with_profile: TestClient) -> None:
        resp = client_with_profile.get("/api/sources/list")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        names = [s["name"] for s in data]
        assert "jobbank" in names

    def test_sources_have_class_names(self, client_with_profile: TestClient) -> None:
        resp = client_with_profile.get("/api/sources/list")
        data = resp.json()
        for source in data:
            assert "name" in source
            assert "class" in source


# ---------------------------------------------------------------------------
# Scan endpoint
# ---------------------------------------------------------------------------


class TestScanEndpoint:
    def test_scan_unknown_source(self, client_with_profile: TestClient) -> None:
        resp = client_with_profile.post(
            "/api/sources/scan",
            data={"source_name": "nonexistent", "keywords": "Python"},
        )
        assert resp.status_code == 400
        assert "Unknown source" in resp.text

    def test_scan_no_keywords_no_profile(self, client_no_profile: TestClient) -> None:
        resp = client_no_profile.post(
            "/api/sources/scan",
            data={"source_name": "jobbank", "keywords": ""},
        )
        assert resp.status_code == 400
        assert "No keywords" in resp.text

    def test_scan_returns_sse_stream(self, client_with_profile: TestClient) -> None:
        """Scan with a mock source should return an SSE stream."""
        from emplaiyed.core.models import Opportunity
        from datetime import datetime

        mock_opp = Opportunity(
            id="opp-test-1",
            source="jobbank",
            source_url="https://example.com/job/1",
            company="TestCo",
            title="Backend Engineer",
            description="Build stuff",
            location="Montreal",
            scraped_at=datetime.now(),
        )

        with patch("emplaiyed.api.routes.sources.get_available_sources") as mock_get:
            mock_source = AsyncMock()
            mock_source.name = "jobbank"
            mock_source.scrape_and_persist = AsyncMock(return_value=[mock_opp])
            mock_get.return_value = {"jobbank": mock_source}

            resp = client_with_profile.post(
                "/api/sources/scan",
                data={
                    "source_name": "jobbank",
                    "keywords": "Python",
                    "location": "Montreal",
                },
            )

            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            # SSE data should contain progress messages
            body = resp.text
            assert "event: progress" in body or "event: done" in body


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    def test_search_requires_profile(self, client_no_profile: TestClient) -> None:
        resp = client_no_profile.post(
            "/api/sources/search",
            data={"direction": "find me AI roles"},
        )
        assert resp.status_code == 400
        assert "Profile required" in resp.text

    def test_search_returns_sse_stream(self, client_with_profile: TestClient) -> None:
        """Search with mocked agent should return SSE stream."""
        from emplaiyed.sources.search_agent import SearchResult

        mock_result = SearchResult(
            opportunities=[], queries_used=["test query"], summary="No results"
        )

        with patch("emplaiyed.api.routes.sources.get_available_sources") as mock_get:
            mock_get.return_value = {}

            with patch(
                "emplaiyed.sources.search_agent.agentic_search",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                resp = client_with_profile.post(
                    "/api/sources/search",
                    data={"direction": "find me AI roles", "time_limit": "60"},
                )

                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
                body = resp.text
                assert "event: progress" in body or "event: done" in body
