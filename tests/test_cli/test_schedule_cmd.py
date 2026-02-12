"""Tests for the schedule and calendar CLI commands."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from emplaiyed.core.database import (
    get_application,
    init_db,
    list_events,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
    ScheduledEvent,
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
        company="Coveo",
        title="Applied ML Engineer",
        description="Build ML pipelines",
        location="Montreal",
        scraped_at=datetime(2025, 1, 15, 10, 30, 0),
    )


@pytest.fixture
def sample_application() -> Application:
    return Application(
        id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee",
        opportunity_id="opp-1",
        status=ApplicationStatus.RESPONSE_RECEIVED,
        created_at=datetime(2025, 1, 15, 11, 0, 0),
        updated_at=datetime(2025, 1, 15, 11, 0, 0),
    )


def _patch_db(db_path: Path):
    """Return a patch context manager that makes schedule commands use the given DB."""
    return patch(
        "emplaiyed.cli.schedule_cmd.get_default_db_path",
        return_value=db_path,
    )


# ---------------------------------------------------------------------------
# schedule command
# ---------------------------------------------------------------------------


class TestScheduleCommand:
    def test_schedule_creates_event(
        self, tmp_path: Path, sample_opportunity, sample_application
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee",
                    "--type", "phone_screen",
                    "--date", "2025-01-14 14:00",
                    "--notes", "With Sarah Chen, Talent Acquisition",
                ],
            )
        assert result.exit_code == 0
        assert "Phone Screen" in result.output
        assert "Coveo" in result.output
        assert "Applied ML Engineer" in result.output

        # Verify event was created in DB
        events = list_events(conn, application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee")
        assert len(events) == 1
        assert events[0].event_type == "phone_screen"
        assert events[0].notes == "With Sarah Chen, Talent Acquisition"
        conn.close()

    def test_schedule_with_prefix_matching(
        self, tmp_path: Path, sample_opportunity, sample_application
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "a3f8c2d1",
                    "--type", "technical_interview",
                    "--date", "2025-01-16 10:00",
                ],
            )
        assert result.exit_code == 0
        assert "Technical Interview" in result.output
        assert "Coveo" in result.output

        # Verify event was created
        events = list_events(conn, application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee")
        assert len(events) == 1
        conn.close()

    def test_schedule_auto_transitions_to_interview_scheduled(
        self, tmp_path: Path, sample_opportunity, sample_application
    ):
        """When scheduling for an app in RESPONSE_RECEIVED, it should auto-transition."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "a3f8c2d1",
                    "--type", "phone_screen",
                    "--date", "2025-01-14 14:00",
                ],
            )
        assert result.exit_code == 0

        # Verify status was transitioned
        loaded = get_application(conn, "a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee")
        assert loaded.status == ApplicationStatus.INTERVIEW_SCHEDULED
        conn.close()

    def test_schedule_does_not_transition_when_inappropriate(
        self, tmp_path: Path, sample_opportunity
    ):
        """When the app status cannot transition to INTERVIEW_SCHEDULED, don't change it."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)

        # Application in DISCOVERED status cannot transition to INTERVIEW_SCHEDULED
        app_obj = Application(
            id="app-discovered",
            opportunity_id="opp-1",
            status=ApplicationStatus.DISCOVERED,
            created_at=datetime(2025, 1, 15, 11, 0, 0),
            updated_at=datetime(2025, 1, 15, 11, 0, 0),
        )
        save_application(conn, app_obj)

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "app-discovered",
                    "--type", "follow_up_due",
                    "--date", "2025-01-17 00:00",
                ],
            )
        assert result.exit_code == 0

        # Status should remain DISCOVERED
        loaded = get_application(conn, "app-discovered")
        assert loaded.status == ApplicationStatus.DISCOVERED
        conn.close()

    def test_schedule_nonexistent_application(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        init_db(db_path)

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "does-not-exist",
                    "--type", "phone_screen",
                    "--date", "2025-01-14 14:00",
                ],
            )
        assert result.exit_code == 1
        assert "Application not found" in result.output

    def test_schedule_invalid_date(self, tmp_path: Path, sample_opportunity, sample_application):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "a3f8c2d1",
                    "--type", "phone_screen",
                    "--date", "not-a-date",
                ],
            )
        assert result.exit_code == 1
        assert "Invalid date format" in result.output

    def test_schedule_without_notes(
        self, tmp_path: Path, sample_opportunity, sample_application
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "a3f8c2d1",
                    "--type", "onsite",
                    "--date", "2025-01-20 09:00",
                ],
            )
        assert result.exit_code == 0
        assert "Onsite" in result.output

        events = list_events(conn, application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee")
        assert len(events) == 1
        assert events[0].notes is None
        conn.close()

    def test_schedule_ambiguous_prefix(self, tmp_path: Path, sample_opportunity):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)

        # Create two apps with same prefix
        for suffix in ["aaaa", "aabb"]:
            save_application(conn, Application(
                id=f"same-prefix-{suffix}",
                opportunity_id="opp-1",
                status=ApplicationStatus.RESPONSE_RECEIVED,
                created_at=datetime(2025, 1, 15, 11, 0, 0),
                updated_at=datetime(2025, 1, 15, 11, 0, 0),
            ))
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(
                app,
                [
                    "schedule",
                    "same-prefix",
                    "--type", "phone_screen",
                    "--date", "2025-01-14 14:00",
                ],
            )
        assert result.exit_code == 1
        assert "Ambiguous ID" in result.output


# ---------------------------------------------------------------------------
# calendar command
# ---------------------------------------------------------------------------


class TestCalendarCommand:
    def test_calendar_shows_upcoming_events(
        self, tmp_path: Path, sample_opportunity, sample_application
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        from emplaiyed.core.database import save_event

        # Create a future event
        save_event(conn, ScheduledEvent(
            id="evt-1",
            application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee",
            event_type="phone_screen",
            scheduled_date=datetime(2099, 1, 14, 14, 0, 0),
            notes="With Sarah Chen",
            created_at=datetime(2099, 1, 10, 10, 0, 0),
        ))
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["calendar"])
        assert result.exit_code == 0
        assert "Upcoming Events" in result.output
        assert "Coveo" in result.output
        assert "Phone Screen" in result.output
        assert "a3f8c2d1" in result.output

    def test_calendar_no_events(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        init_db(db_path)

        with _patch_db(db_path):
            result = runner.invoke(app, ["calendar"])
        assert result.exit_code == 0
        assert "No upcoming events" in result.output

    def test_calendar_only_future_events(
        self, tmp_path: Path, sample_opportunity, sample_application
    ):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        from emplaiyed.core.database import save_event

        # Past event
        save_event(conn, ScheduledEvent(
            id="evt-past",
            application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee",
            event_type="phone_screen",
            scheduled_date=datetime(2020, 1, 1, 10, 0, 0),
            created_at=datetime(2019, 12, 28, 10, 0, 0),
        ))
        # Future event
        save_event(conn, ScheduledEvent(
            id="evt-future",
            application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee",
            event_type="technical_interview",
            scheduled_date=datetime(2099, 6, 15, 10, 0, 0),
            created_at=datetime(2099, 6, 1, 10, 0, 0),
        ))
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["calendar"])
        assert result.exit_code == 0
        assert "Technical Interview" in result.output
        # The past event should not show "Phone Screen"
        assert "Phone Screen" not in result.output

    def test_calendar_multiple_events(self, tmp_path: Path, sample_opportunity):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)

        # Create a second opportunity and application
        opp2 = Opportunity(
            id="opp-2",
            source="linkedin",
            company="Intact",
            title="Data Engineer",
            description="Build data pipelines",
            scraped_at=datetime(2025, 1, 15, 10, 30, 0),
        )
        save_opportunity(conn, opp2)

        app1 = Application(
            id="app-1111",
            opportunity_id="opp-1",
            status=ApplicationStatus.INTERVIEW_SCHEDULED,
            created_at=datetime(2025, 1, 15, 11, 0, 0),
            updated_at=datetime(2025, 1, 15, 11, 0, 0),
        )
        app2 = Application(
            id="app-2222",
            opportunity_id="opp-2",
            status=ApplicationStatus.INTERVIEW_SCHEDULED,
            created_at=datetime(2025, 1, 15, 11, 0, 0),
            updated_at=datetime(2025, 1, 15, 11, 0, 0),
        )
        save_application(conn, app1)
        save_application(conn, app2)

        from emplaiyed.core.database import save_event

        save_event(conn, ScheduledEvent(
            id="evt-1",
            application_id="app-1111",
            event_type="phone_screen",
            scheduled_date=datetime(2099, 1, 14, 14, 0, 0),
            created_at=datetime(2099, 1, 10, 10, 0, 0),
        ))
        save_event(conn, ScheduledEvent(
            id="evt-2",
            application_id="app-2222",
            event_type="technical_interview",
            scheduled_date=datetime(2099, 1, 16, 10, 0, 0),
            created_at=datetime(2099, 1, 10, 10, 0, 0),
        ))
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["calendar"])
        assert result.exit_code == 0
        assert "Coveo" in result.output
        assert "Intact" in result.output
        assert "Phone Screen" in result.output
        assert "Technical Interview" in result.output

    def test_calendar_midnight_shows_dash(self, tmp_path: Path, sample_opportunity, sample_application):
        """Events at midnight should show a dash for the time (e.g. follow-up due dates)."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_opportunity(conn, sample_opportunity)
        save_application(conn, sample_application)

        from emplaiyed.core.database import save_event

        save_event(conn, ScheduledEvent(
            id="evt-midnight",
            application_id="a3f8c2d1-aaaa-bbbb-cccc-ddddeeeeeeee",
            event_type="follow_up_due",
            scheduled_date=datetime(2099, 1, 17, 0, 0, 0),
            created_at=datetime(2099, 1, 10, 10, 0, 0),
        ))
        conn.close()

        with _patch_db(db_path):
            result = runner.invoke(app, ["calendar"])
        assert result.exit_code == 0
        # The dash character (em dash) should appear for midnight times
        assert "\u2014" in result.output
        assert "Follow Up Due" in result.output
