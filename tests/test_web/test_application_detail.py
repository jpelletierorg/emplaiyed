"""Tests for the application detail page and action endpoints."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Aspirations,
    Opportunity,
    Profile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    # First init the schema via the normal helper …
    conn = init_db(tmp_path / "test.db")
    conn.close()
    # … then re-open with check_same_thread=False so the TestClient
    # (which runs endpoints in a different thread) can use the same conn.
    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@pytest.fixture
def sample_opp() -> Opportunity:
    return Opportunity(
        id="opp-test-detail",
        source="jobbank",
        source_url="https://example.com/job/123",
        company="DetailCo",
        title="Staff Engineer",
        description="Build amazing distributed systems.\n\nRequirements:\n- Python\n- AWS",
        location="Montreal, QC",
        salary_min=120000,
        salary_max=160000,
        scraped_at=datetime(2025, 6, 1, 10, 0, 0),
    )


@pytest.fixture
def sample_app() -> Application:
    return Application(
        id="app-test-detail-1234",
        opportunity_id="opp-test-detail",
        status=ApplicationStatus.SCORED,
        score=82,
        justification="Strong match for distributed systems background.",
        day_to_day="Design and implement microservices, mentor junior engineers.",
        why_it_fits="Candidate's Python and AWS experience aligns well with the role.",
        created_at=datetime(2025, 6, 1, 11, 0, 0),
        updated_at=datetime(2025, 6, 1, 11, 0, 0),
    )


def _make_db_override(conn: sqlite3.Connection):
    def override():
        yield conn

    return override


@pytest.fixture
def client_with_data(
    tmp_db: sqlite3.Connection,
    sample_opp: Opportunity,
    sample_app: Application,
    tmp_path: Path,
) -> TestClient:
    """TestClient with an opportunity and application in the database."""
    save_opportunity(tmp_db, sample_opp)
    save_application(tmp_db, sample_app)

    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


@pytest.fixture
def sample_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        aspirations=Aspirations(target_roles=["Staff Engineer"]),
    )


@pytest.fixture
def client_with_profile(
    tmp_db: sqlite3.Connection,
    sample_opp: Opportunity,
    sample_app: Application,
    sample_profile: Profile,
    tmp_path: Path,
) -> TestClient:
    """TestClient with data AND a profile (needed for generation)."""
    save_opportunity(tmp_db, sample_opp)
    save_application(tmp_db, sample_app)

    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: sample_profile
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
# Tests
# ---------------------------------------------------------------------------


class TestApplicationDetail:
    def test_detail_page_renders(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        # Company and title should be visible
        assert "DetailCo" in resp.text
        assert "Staff Engineer" in resp.text

    def test_shows_score(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "82" in resp.text

    def test_shows_status(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "SCORED" in resp.text

    def test_shows_ai_assessment(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "Strong match" in resp.text
        assert "microservices" in resp.text
        assert "Python and AWS" in resp.text

    def test_shows_salary(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "120,000" in resp.text
        assert "160,000" in resp.text

    def test_shows_location(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "Montreal" in resp.text

    def test_shows_job_description(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "distributed systems" in resp.text

    def test_shows_source_link(self, client_with_data: TestClient) -> None:
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "https://example.com/job/123" in resp.text

    def test_shows_action_buttons(self, client_with_data: TestClient) -> None:
        """SCORED status should show valid transition buttons."""
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        # SCORED can transition to OUTREACH_PENDING, OUTREACH_SENT, BELOW_THRESHOLD, PASSED
        assert "transition" in resp.text.lower()

    def test_not_found(self, client_empty: TestClient) -> None:
        resp = client_empty.get("/applications/nonexistent-id")
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()


# ---------------------------------------------------------------------------
# Transition endpoint tests
# ---------------------------------------------------------------------------


class TestTransitionEndpoint:
    def test_valid_transition(self, client_with_data: TestClient) -> None:
        """SCORED -> PASSED is a valid transition."""
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/transition",
            data={"target_status": "PASSED"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/applications/app-test-detail-1234"

    def test_transition_updates_status(
        self, client_with_data: TestClient, tmp_db: sqlite3.Connection
    ) -> None:
        """After a transition, the DB should reflect the new status."""
        client_with_data.post(
            "/api/applications/app-test-detail-1234/transition",
            data={"target_status": "OUTREACH_PENDING"},
        )
        from emplaiyed.core.database import get_application

        app = get_application(tmp_db, "app-test-detail-1234")
        assert app is not None
        assert app.status.value == "OUTREACH_PENDING"

    def test_invalid_target_status(self, client_with_data: TestClient) -> None:
        """Non-existent status string should return 400."""
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/transition",
            data={"target_status": "BOGUS_STATUS"},
        )
        assert resp.status_code == 400
        assert "Invalid status" in resp.text

    def test_invalid_transition(self, client_with_data: TestClient) -> None:
        """SCORED -> ACCEPTED is not a valid transition."""
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/transition",
            data={"target_status": "ACCEPTED"},
        )
        assert resp.status_code == 422
        assert "Cannot transition" in resp.text

    def test_transition_not_found(self, client_empty: TestClient) -> None:
        """Transitioning a nonexistent application should return 404."""
        resp = client_empty.post(
            "/api/applications/nonexistent-id/transition",
            data={"target_status": "PASSED"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Notes endpoint tests
# ---------------------------------------------------------------------------


class TestNotesEndpoint:
    def test_add_note(
        self, client_with_data: TestClient, tmp_db: sqlite3.Connection
    ) -> None:
        """Adding a note should create an interaction in the DB."""
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/notes",
            data={"content": "Remember to follow up next week"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/applications/app-test-detail-1234"

        interactions = list_interactions(tmp_db, "app-test-detail-1234")
        assert len(interactions) == 1
        assert interactions[0].type.value == "NOTE"
        assert interactions[0].content == "Remember to follow up next week"
        assert interactions[0].channel == "web"

    def test_add_note_appears_in_timeline(self, client_with_data: TestClient) -> None:
        """After adding a note, it should appear in the detail page timeline."""
        client_with_data.post(
            "/api/applications/app-test-detail-1234/notes",
            data={"content": "Recruiter seemed interested"},
        )
        resp = client_with_data.get("/applications/app-test-detail-1234")
        assert resp.status_code == 200
        assert "Recruiter seemed interested" in resp.text

    def test_add_empty_note(self, client_with_data: TestClient) -> None:
        """Empty notes should be rejected."""
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/notes",
            data={"content": "   "},
        )
        assert resp.status_code == 400

    def test_add_note_not_found(self, client_empty: TestClient) -> None:
        """Adding a note to a nonexistent application should return 404."""
        resp = client_empty.post(
            "/api/applications/nonexistent-id/notes",
            data={"content": "Some note"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete endpoint tests
# ---------------------------------------------------------------------------


class TestDeleteEndpoint:
    def test_delete_application(
        self, client_with_data: TestClient, tmp_db: sqlite3.Connection
    ) -> None:
        """Deleting should remove the application from the DB."""
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/delete",
        )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/queue"

        app = get_application(tmp_db, "app-test-detail-1234")
        assert app is None

    def test_delete_not_found(self, client_empty: TestClient) -> None:
        """Deleting a nonexistent application should return 404."""
        resp = client_empty.post(
            "/api/applications/nonexistent-id/delete",
        )
        assert resp.status_code == 404

    def test_delete_removes_assets(
        self,
        client_with_data: TestClient,
        tmp_path: Path,
    ) -> None:
        """Deleting should clean up the asset directory."""
        # Create a fake asset directory
        asset_dir = tmp_path / "data" / "assets" / "app-test-detail-1234"
        asset_dir.mkdir(parents=True)
        (asset_dir / "cv.pdf").write_bytes(b"fake")

        with patch(
            "emplaiyed.api.routes.applications.get_asset_dir",
            return_value=asset_dir,
        ):
            resp = client_with_data.post(
                "/api/applications/app-test-detail-1234/delete",
            )

        assert resp.status_code == 200
        assert not asset_dir.exists()


# ---------------------------------------------------------------------------
# Generate endpoint tests
# ---------------------------------------------------------------------------


class TestGenerateEndpoint:
    def test_generate_no_profile(self, client_with_data: TestClient) -> None:
        """Generating without a profile should return 400."""
        # client_with_data has profile=None
        resp = client_with_data.post(
            "/api/applications/app-test-detail-1234/generate",
        )
        assert resp.status_code == 400
        assert "profile" in resp.text.lower()

    def test_generate_not_found(self, client_empty: TestClient) -> None:
        """Generating for a nonexistent application should return 404."""
        resp = client_empty.post(
            "/api/applications/nonexistent-id/generate",
        )
        assert resp.status_code == 404

    def test_generate_already_exists(self, client_with_profile: TestClient) -> None:
        """If assets already exist, should redirect without regenerating."""
        with patch("emplaiyed.api.routes.applications.has_assets", return_value=True):
            resp = client_with_profile.post(
                "/api/applications/app-test-detail-1234/generate",
            )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/applications/app-test-detail-1234"

    def test_generate_success(self, client_with_profile: TestClient) -> None:
        """Successful generation should redirect back to the detail page."""
        mock_paths = AsyncMock()
        with (
            patch(
                "emplaiyed.api.routes.applications.has_assets",
                return_value=False,
            ),
            patch(
                "emplaiyed.api.routes.applications.generate_assets",
                new_callable=AsyncMock,
                return_value=mock_paths,
            ),
        ):
            resp = client_with_profile.post(
                "/api/applications/app-test-detail-1234/generate",
            )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/applications/app-test-detail-1234"

    def test_generate_failure(self, client_with_profile: TestClient) -> None:
        """If generation raises, should return 500 with error message."""
        with (
            patch(
                "emplaiyed.api.routes.applications.has_assets",
                return_value=False,
            ),
            patch(
                "emplaiyed.api.routes.applications.generate_assets",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM timeout"),
            ),
        ):
            resp = client_with_profile.post(
                "/api/applications/app-test-detail-1234/generate",
            )
        assert resp.status_code == 500
        assert "LLM timeout" in resp.text
