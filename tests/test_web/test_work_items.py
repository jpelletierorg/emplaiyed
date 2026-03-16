"""Tests for the work queue page and work item action endpoints."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emplaiyed.api.app import create_app
from emplaiyed.api.deps import get_db, get_profile, get_data_dir
from emplaiyed.core.database import (
    get_application,
    init_db,
    list_interactions,
    save_application,
    save_opportunity,
    save_work_item,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
    WorkItem,
    WorkStatus,
    WorkType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "test.db")
    conn.close()
    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@pytest.fixture
def sample_opp() -> Opportunity:
    return Opportunity(
        id="opp-work-test",
        source="jobbank",
        source_url="https://example.com/job/456",
        company="WorkCo",
        title="Backend Developer",
        description="Build APIs",
        location="Toronto, ON",
        scraped_at=datetime(2025, 6, 1, 10, 0, 0),
    )


@pytest.fixture
def sample_app() -> Application:
    return Application(
        id="app-work-test-1",
        opportunity_id="opp-work-test",
        status=ApplicationStatus.OUTREACH_PENDING,
        score=75,
        created_at=datetime(2025, 6, 1, 11, 0, 0),
        updated_at=datetime(2025, 6, 1, 11, 0, 0),
    )


@pytest.fixture
def sample_work_item() -> WorkItem:
    return WorkItem(
        id="wi-test-1",
        application_id="app-work-test-1",
        work_type=WorkType.OUTREACH,
        status=WorkStatus.PENDING,
        title="Send outreach email to WorkCo",
        instructions="Draft an email to the hiring manager.\n\nMention your Python experience.",
        draft_content="Dear Hiring Manager,\n\nI am writing to express my interest...",
        target_status="OUTREACH_SENT",
        previous_status="SCORED",
        created_at=datetime(2025, 6, 1, 12, 0, 0),
    )


def _make_db_override(conn: sqlite3.Connection):
    def override():
        yield conn

    return override


@pytest.fixture
def client_with_work(
    tmp_db: sqlite3.Connection,
    sample_opp: Opportunity,
    sample_app: Application,
    sample_work_item: WorkItem,
    tmp_path: Path,
) -> TestClient:
    """TestClient with an opportunity, application, and work item."""
    save_opportunity(tmp_db, sample_opp)
    save_application(tmp_db, sample_app)
    save_work_item(tmp_db, sample_work_item)

    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


@pytest.fixture
def client_empty(
    tmp_db: sqlite3.Connection,
    tmp_path: Path,
) -> TestClient:
    """TestClient with empty database."""
    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


# ---------------------------------------------------------------------------
# Work page tests
# ---------------------------------------------------------------------------


class TestWorkPage:
    def test_page_renders_with_items(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "Work Queue" in resp.text
        assert "1 pending" in resp.text

    def test_shows_work_item_title(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "Send outreach email to WorkCo" in resp.text

    def test_shows_company_info(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "WorkCo" in resp.text
        assert "Backend Developer" in resp.text

    def test_shows_work_type(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "OUTREACH" in resp.text

    def test_shows_instructions(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "Draft an email" in resp.text

    def test_shows_action_buttons(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "Done" in resp.text
        assert "Skip" in resp.text

    def test_empty_queue(self, client_empty: TestClient) -> None:
        resp = client_empty.get("/work")
        assert resp.status_code == 200
        assert "0 pending" in resp.text
        assert "All caught up" in resp.text

    def test_shows_score(self, client_with_work: TestClient) -> None:
        resp = client_with_work.get("/work")
        assert resp.status_code == 200
        assert "75" in resp.text


# ---------------------------------------------------------------------------
# Complete endpoint tests
# ---------------------------------------------------------------------------


class TestCompleteEndpoint:
    def test_complete_work_item(
        self, client_with_work: TestClient, tmp_db: sqlite3.Connection
    ) -> None:
        """Completing a work item should advance the application status."""
        resp = client_with_work.post("/api/work-items/wi-test-1/complete")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/work"

        # Application should now be OUTREACH_SENT
        app = get_application(tmp_db, "app-work-test-1")
        assert app is not None
        assert app.status == ApplicationStatus.OUTREACH_SENT

    def test_complete_records_interaction(
        self, client_with_work: TestClient, tmp_db: sqlite3.Connection
    ) -> None:
        """Completing should record an interaction."""
        client_with_work.post("/api/work-items/wi-test-1/complete")

        interactions = list_interactions(tmp_db, "app-work-test-1")
        assert len(interactions) >= 1
        assert interactions[0].type.value == "EMAIL_SENT"

    def test_complete_not_found(self, client_empty: TestClient) -> None:
        resp = client_empty.post("/api/work-items/nonexistent/complete")
        assert resp.status_code == 400

    def test_complete_already_completed(self, client_with_work: TestClient) -> None:
        """Completing twice should fail."""
        client_with_work.post("/api/work-items/wi-test-1/complete")
        resp = client_with_work.post("/api/work-items/wi-test-1/complete")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Skip endpoint tests
# ---------------------------------------------------------------------------


class TestSkipEndpoint:
    def test_skip_work_item(
        self, client_with_work: TestClient, tmp_db: sqlite3.Connection
    ) -> None:
        """Skipping should revert the application status."""
        resp = client_with_work.post("/api/work-items/wi-test-1/skip")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/work"

        # Application should revert to SCORED
        app = get_application(tmp_db, "app-work-test-1")
        assert app is not None
        assert app.status == ApplicationStatus.SCORED

    def test_skip_not_found(self, client_empty: TestClient) -> None:
        resp = client_empty.post("/api/work-items/nonexistent/skip")
        assert resp.status_code == 400

    def test_skip_already_skipped(self, client_with_work: TestClient) -> None:
        """Skipping twice should fail."""
        client_with_work.post("/api/work-items/wi-test-1/skip")
        resp = client_with_work.post("/api/work-items/wi-test-1/skip")
        assert resp.status_code == 400
