"""Tests for the funnel CLI subcommands."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from emplaiyed.core.database import (
    init_db,
    save_application,
    save_interaction,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Opportunity,
)
from emplaiyed.main import app

runner = CliRunner()


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


@pytest.fixture
def sample_opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
        source="indeed",
        source_url="https://indeed.com/job/123",
        company="Acme Corp",
        title="Backend Developer",
        description="Build REST APIs",
        location="Montreal",
        salary_min=80000,
        salary_max=110000,
        scraped_at=datetime(2025, 1, 15, 10, 30, 0),
    )


@pytest.fixture
def sample_application() -> Application:
    return Application(
        id="app-00001111-2222-3333-4444-555566667777",
        opportunity_id="opp-1",
        status=ApplicationStatus.DISCOVERED,
        created_at=datetime(2025, 1, 15, 11, 0, 0),
        updated_at=datetime(2025, 1, 15, 11, 0, 0),
    )


@pytest.fixture
def sample_interaction() -> Interaction:
    return Interaction(
        id="int-1",
        application_id="app-00001111-2222-3333-4444-555566667777",
        type=InteractionType.EMAIL_SENT,
        direction="outbound",
        channel="email",
        content="Dear hiring manager, I am writing to express my interest...",
        metadata={"subject": "Application for Backend Developer", "to": "hr@acme.com"},
        created_at=datetime(2025, 1, 16, 9, 0, 0),
    )


def _patch_db(db_path: Path):
    """Return a patch context manager that makes funnel commands use the given DB."""
    return patch(
        "emplaiyed.cli.funnel_cmd.get_default_db_path",
        return_value=db_path,
    )


# ---------------------------------------------------------------------------
# funnel status
# ---------------------------------------------------------------------------


class TestFunnelStatus:
    def test_empty_database(self, tmp_path: Path):
        db_path = tmp_path / "empty.db"
        init_db(db_path)
        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "status"])
        assert result.exit_code == 0
        assert "No applications tracked yet" in result.output

    def test_with_applications(self, tmp_path: Path, sample_opportunity, sample_application):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        # Add a second application with a different status
        app2 = Application(
            id="app-2",
            opportunity_id="opp-1",
            status=ApplicationStatus.SCORED,
            created_at=datetime(2025, 1, 16, 11, 0, 0),
            updated_at=datetime(2025, 1, 16, 11, 0, 0),
        )
        save_application(conn, app2)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "status"])
        assert result.exit_code == 0
        assert "DISCOVERED" in result.output
        assert "SCORED" in result.output
        assert "TOTAL" in result.output

    def test_shows_all_stages(self, tmp_path: Path, sample_opportunity, sample_application):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "status"])
        assert result.exit_code == 0
        # All stages should be listed, even if count is 0
        for status in ApplicationStatus:
            assert status.value in result.output


# ---------------------------------------------------------------------------
# funnel list
# ---------------------------------------------------------------------------


class TestFunnelList:
    def test_empty_database(self, tmp_path: Path):
        db_path = tmp_path / "empty.db"
        init_db(db_path)
        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "list"])
        assert result.exit_code == 0
        assert "No applications tracked yet" in result.output

    def test_with_data(self, tmp_path: Path, sample_opportunity, sample_application):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "list"])
        assert result.exit_code == 0
        assert "Acme Corp" in result.output
        assert "Backend Developer" in result.output
        assert "DISCOVERED" in result.output
        # Should show first 8 chars of the ID
        assert "app-0000" in result.output

    def test_filter_by_stage(self, tmp_path: Path, sample_opportunity, sample_application):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        scored_app = Application(
            id="app-scored-1",
            opportunity_id="opp-1",
            status=ApplicationStatus.SCORED,
            created_at=datetime(2025, 1, 16, 11, 0, 0),
            updated_at=datetime(2025, 1, 16, 11, 0, 0),
        )
        save_application(conn, scored_app)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "list", "--stage", "SCORED"])
        assert result.exit_code == 0
        assert "SCORED" in result.output
        # The DISCOVERED application should NOT appear
        assert "DISCOVERED" not in result.output

    def test_filter_by_stage_no_results(self, tmp_path: Path, sample_opportunity, sample_application):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "list", "--stage", "GHOSTED"])
        assert result.exit_code == 0
        assert "No applications with stage" in result.output

    def test_invalid_stage(self, tmp_path: Path):
        db_path = tmp_path / "empty.db"
        init_db(db_path)
        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "list", "--stage", "BOGUS"])
        assert result.exit_code == 1
        assert "Invalid stage" in result.output


# ---------------------------------------------------------------------------
# funnel show
# ---------------------------------------------------------------------------


class TestFunnelShow:
    def test_valid_application(
        self,
        tmp_path: Path,
        sample_opportunity,
        sample_application,
        sample_interaction,
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        save_interaction(conn, sample_interaction)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                ["funnel", "show", "app-00001111-2222-3333-4444-555566667777"],
            )
        assert result.exit_code == 0
        assert "Acme Corp" in result.output
        assert "Backend Developer" in result.output
        assert "DISCOVERED" in result.output
        assert "Montreal" in result.output
        assert "EMAIL_SENT" in result.output
        assert "hiring manager" in result.output

    def test_prefix_match(
        self,
        tmp_path: Path,
        sample_opportunity,
        sample_application,
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "show", "app-0000"])
        assert result.exit_code == 0
        assert "Acme Corp" in result.output

    def test_nonexistent_id(self, tmp_path: Path):
        db_path = tmp_path / "empty.db"
        init_db(db_path)
        with _patch_db(db_path):
            result = runner.invoke(app, ["funnel", "show", "does-not-exist"])
        assert result.exit_code == 1
        assert "Application not found" in result.output

    def test_no_interactions(
        self,
        tmp_path: Path,
        sample_opportunity,
        sample_application,
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                ["funnel", "show", "app-00001111-2222-3333-4444-555566667777"],
            )
        assert result.exit_code == 0
        assert "No interactions recorded yet" in result.output
