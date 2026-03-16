"""Tests for profile web routes (Phase 2).

Validates that all profile endpoints return correct HTTP status codes and
render expected content.  Uses FastAPI TestClient with dependency overrides
to inject a temp database and profile.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emplaiyed.api.app import create_app
from emplaiyed.api.deps import get_db, get_profile, get_profile_path, get_data_dir
from emplaiyed.core.database import init_db
from emplaiyed.core.models import (
    Address,
    Aspirations,
    Certification,
    Education,
    Employment,
    Language,
    Profile,
)
from emplaiyed.core.profile_store import save_profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a temp database for testing."""
    return init_db(tmp_path / "test.db")


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    return tmp_path / "profile.yaml"


@pytest.fixture
def sample_profile() -> Profile:
    """A populated profile for testing."""
    return Profile(
        name="Test User",
        email="test@example.com",
        phone="+1-555-0100",
        address=Address(city="Montreal", province_state="QC", country="Canada"),
        skills=["Python", "FastAPI", "Docker"],
        languages=[Language(language="English", proficiency="native")],
        education=[
            Education(
                institution="MIT",
                degree="BSc",
                field="CS",
                start_date=date(2010, 9, 1),
                end_date=date(2014, 6, 1),
            ),
        ],
        employment_history=[
            Employment(
                company="BigCo",
                title="Senior Engineer",
                start_date=date(2015, 1, 1),
                highlights=["Built a thing", "Led a team"],
            ),
        ],
        certifications=[Certification(name="AWS SAA", issuer="Amazon")],
        aspirations=Aspirations(
            target_roles=["Staff Engineer"],
            salary_minimum=100000,
            salary_target=130000,
            urgency="within_3_months",
            geographic_preferences=["Montreal", "Remote"],
            work_arrangement=["hybrid"],
            statement="I want to build great software.",
        ),
    )


@pytest.fixture
def client_with_profile(
    tmp_db: sqlite3.Connection,
    profile_path: Path,
    sample_profile: Profile,
    tmp_path: Path,
) -> TestClient:
    """TestClient with a populated profile."""
    save_profile(sample_profile, profile_path)
    app = create_app()

    def _db_override():
        yield tmp_db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_profile] = lambda: sample_profile
    app.dependency_overrides[get_profile_path] = lambda: profile_path
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


@pytest.fixture
def client_no_profile(
    tmp_db: sqlite3.Connection,
    profile_path: Path,
    tmp_path: Path,
) -> TestClient:
    """TestClient with no profile."""
    app = create_app()
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_profile_path] = lambda: profile_path
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


# ---------------------------------------------------------------------------
# Profile edit page
# ---------------------------------------------------------------------------


class TestProfileEditPage:
    def test_edit_page_renders(self, client_with_profile: TestClient) -> None:
        resp = client_with_profile.get("/profile/edit")
        assert resp.status_code == 200
        assert "Test User" in resp.text
        assert "test@example.com" in resp.text

    def test_edit_page_redirects_without_profile(
        self, client_no_profile: TestClient
    ) -> None:
        resp = client_no_profile.get("/profile/edit", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/profile/build"


class TestProfileSave:
    def test_save_redirects_to_profile(
        self,
        client_with_profile: TestClient,
        profile_path: Path,
    ) -> None:
        resp = client_with_profile.post(
            "/api/profile/save",
            data={
                "name": "Updated Name",
                "email": "updated@example.com",
                "skills": "Python, Go, Rust",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/profile"

        # Verify the profile was updated on disk
        from emplaiyed.core.profile_store import load_profile

        updated = load_profile(profile_path)
        assert updated.name == "Updated Name"
        assert updated.email == "updated@example.com"
        assert "Rust" in updated.skills


# ---------------------------------------------------------------------------
# Build wizard
# ---------------------------------------------------------------------------


class TestBuildWizard:
    def test_wizard_start_renders(self, client_no_profile: TestClient) -> None:
        resp = client_no_profile.get("/profile/build")
        assert resp.status_code == 200
        # Should show upload form
        assert "upload" in resp.text.lower() or "cv" in resp.text.lower()

    def test_wizard_start_with_existing_profile(
        self, client_with_profile: TestClient
    ) -> None:
        resp = client_with_profile.get("/profile/build")
        assert resp.status_code == 200

    def test_fresh_start_shows_basics(self, client_no_profile: TestClient) -> None:
        """Posting empty CV data should redirect to basics (step 2)."""
        resp = client_no_profile.post(
            "/api/profile/build/upload",
            data={"cv_text": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        # Should render basics form (name + email)
        assert "name" in resp.text.lower()

    def test_basics_redirects_to_gaps(self, client_no_profile: TestClient) -> None:
        resp = client_no_profile.post(
            "/api/profile/build/basics",
            data={"name": "New User", "email": "new@example.com"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/profile/build/gaps"


# ---------------------------------------------------------------------------
# Gaps page
# ---------------------------------------------------------------------------


class TestGapsPage:
    def test_gaps_page_redirects_without_wizard_state(
        self, client_no_profile: TestClient
    ) -> None:
        """Going to /profile/build/gaps without wizard state should redirect."""
        # Reset wizard state from any prior test
        from emplaiyed.api.routes.profile import _reset_wizard

        _reset_wizard()
        resp = client_no_profile.get("/profile/build/gaps", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/profile/build"


# ---------------------------------------------------------------------------
# Enhance page
# ---------------------------------------------------------------------------


class TestEnhancePage:
    def test_enhance_page_renders(self, client_with_profile: TestClient) -> None:
        resp = client_with_profile.get("/profile/enhance")
        assert resp.status_code == 200
        assert "enhance" in resp.text.lower() or "highlight" in resp.text.lower()

    def test_enhance_page_redirects_without_profile(
        self, client_no_profile: TestClient
    ) -> None:
        resp = client_no_profile.get("/profile/enhance", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/profile/build"
