"""Tests for CLI work commands — list, next, done, skip."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from emplaiyed.core.database import (
    get_application,
    init_db,
    list_pending_work_items,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
    WorkType,
)
from emplaiyed.main import app
from emplaiyed.work.queue import create_work_item

runner = CliRunner()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db_with_work_item(db_path: Path):
    """Create a DB with one PENDING work item."""
    conn = init_db(db_path)
    opp = Opportunity(
        id="opp-1",
        source="jobbank",
        company="Coveo",
        title="ML Engineer",
        description="Build ML stuff.",
        location="Quebec, QC",
        scraped_at=datetime.now(),
    )
    save_opportunity(conn, opp)

    app_obj = Application(
        id="app-1",
        opportunity_id="opp-1",
        status=ApplicationStatus.SCORED,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    save_application(conn, app_obj)

    item = create_work_item(
        conn,
        application_id="app-1",
        work_type=WorkType.OUTREACH,
        title="Send outreach to Coveo — ML Engineer",
        instructions="Copy the email and send it.",
        draft_content="Subject: Hi\n\nHello from Jonathan.",
        target_status=ApplicationStatus.OUTREACH_SENT,
        previous_status=ApplicationStatus.SCORED,
        pending_status=ApplicationStatus.OUTREACH_PENDING,
    )
    conn.close()
    return item


class TestWorkList:
    def test_empty_queue(self, db_path: Path):
        init_db(db_path).close()
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "list"])
        assert result.exit_code == 0
        assert "all caught up" in result.output.lower()

    def test_shows_pending_items(self, db_path: Path, db_with_work_item):
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "list"])
        assert result.exit_code == 0
        assert "1 pending" in result.output
        assert "Coveo" in result.output


class TestWorkNext:
    def test_shows_oldest_item(self, db_path: Path, db_with_work_item):
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "next"])
        assert result.exit_code == 0
        assert "Coveo" in result.output
        assert "ML Engineer" in result.output

    def test_empty_queue(self, db_path: Path):
        init_db(db_path).close()
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "next"])
        assert result.exit_code == 0
        assert "all caught up" in result.output.lower()


class TestWorkDone:
    def test_completes_item(self, db_path: Path, db_with_work_item):
        item = db_with_work_item
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "done", item.id])
        assert result.exit_code == 0
        assert "Done!" in result.output or "done" in result.output.lower()
        assert "OUTREACH_SENT" in result.output

        # Verify state
        conn = init_db(db_path)
        app_obj = get_application(conn, "app-1")
        assert app_obj.status == ApplicationStatus.OUTREACH_SENT
        assert len(list_pending_work_items(conn)) == 0
        conn.close()

    def test_prefix_match(self, db_path: Path, db_with_work_item):
        item = db_with_work_item
        prefix = item.id[:8]
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "done", prefix])
        assert result.exit_code == 0
        assert "OUTREACH_SENT" in result.output


class TestWorkSkip:
    def test_skips_item(self, db_path: Path, db_with_work_item):
        item = db_with_work_item
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "skip", item.id])
        assert result.exit_code == 0
        assert "Skipped" in result.output or "skipped" in result.output.lower()
        assert "SCORED" in result.output

        # Verify state reverted
        conn = init_db(db_path)
        app_obj = get_application(conn, "app-1")
        assert app_obj.status == ApplicationStatus.SCORED
        assert len(list_pending_work_items(conn)) == 0
        conn.close()


class TestWorkPass:
    def test_passes_scored_application(self, db_path: Path):
        """Mark a SCORED application as PASSED."""
        conn = init_db(db_path)
        opp = Opportunity(
            id="opp-pass",
            source="jobbank",
            company="NoCorp",
            title="Boring Role",
            description="Not interested.",
            scraped_at=datetime.now(),
        )
        save_opportunity(conn, opp)

        app_obj = Application(
            id="app-pass",
            opportunity_id="opp-pass",
            status=ApplicationStatus.SCORED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        save_application(conn, app_obj)
        conn.close()

        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "pass", "app-pass"])
        assert result.exit_code == 0
        assert "Passed" in result.output or "passed" in result.output.lower()
        assert "NoCorp" in result.output

        conn = init_db(db_path)
        updated = get_application(conn, "app-pass")
        assert updated.status == ApplicationStatus.PASSED
        conn.close()

    def test_pass_invalid_state(self, db_path: Path):
        """Cannot pass an application that's already OUTREACH_SENT."""
        conn = init_db(db_path)
        opp = Opportunity(
            id="opp-sent",
            source="jobbank",
            company="SentCorp",
            title="Already Sent",
            description="Already contacted.",
            scraped_at=datetime.now(),
        )
        save_opportunity(conn, opp)

        app_obj = Application(
            id="app-sent",
            opportunity_id="opp-sent",
            status=ApplicationStatus.OUTREACH_SENT,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        save_application(conn, app_obj)
        conn.close()

        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "pass", "app-sent"])
        assert result.exit_code == 1

    def test_pass_prefix_match(self, db_path: Path):
        """Prefix matching works for application IDs."""
        conn = init_db(db_path)
        opp = Opportunity(
            id="opp-prefix",
            source="jobbank",
            company="PrefixCorp",
            title="Some Role",
            description="Test prefix.",
            scraped_at=datetime.now(),
        )
        save_opportunity(conn, opp)

        app_obj = Application(
            id="app-prefix-12345",
            opportunity_id="opp-prefix",
            status=ApplicationStatus.SCORED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        save_application(conn, app_obj)
        conn.close()

        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "pass", "app-prefix"])
        assert result.exit_code == 0
        assert "PrefixCorp" in result.output

    def test_pass_not_found(self, db_path: Path):
        init_db(db_path).close()
        with patch("emplaiyed.cli.get_default_db_path", return_value=db_path):
            result = runner.invoke(app, ["work", "pass", "nonexistent"])
        assert result.exit_code == 1
