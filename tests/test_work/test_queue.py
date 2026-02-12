"""Tests for emplaiyed.work.queue — work queue create/complete/skip."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from emplaiyed.core.database import (
    get_application,
    get_work_item,
    init_db,
    list_interactions,
    list_pending_work_items,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
    WorkStatus,
    WorkType,
)
from emplaiyed.work.queue import complete_work_item, create_work_item, skip_work_item


def _test_opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
        source="jobbank",
        company="Test Corp",
        title="Software Developer",
        description="A job.",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "test.db")
    opp = _test_opportunity()
    save_opportunity(conn, opp)
    return conn


@pytest.fixture
def scored_app(db: sqlite3.Connection) -> Application:
    now = datetime.now()
    app = Application(
        id="app-1",
        opportunity_id="opp-1",
        status=ApplicationStatus.SCORED,
        created_at=now,
        updated_at=now,
    )
    save_application(db, app)
    return app


class TestCreateWorkItem:
    def test_creates_item_and_transitions_to_pending(self, db, scored_app):
        item = create_work_item(
            db,
            application_id="app-1",
            work_type=WorkType.OUTREACH,
            title="Send outreach to Test Corp",
            instructions="Do the thing.",
            draft_content="Subject: Hi\n\nHello.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )

        assert item.status == WorkStatus.PENDING
        assert item.work_type == WorkType.OUTREACH
        assert item.target_status == "OUTREACH_SENT"
        assert item.previous_status == "SCORED"

        # Application should be in OUTREACH_PENDING
        app = get_application(db, "app-1")
        assert app.status == ApplicationStatus.OUTREACH_PENDING

        # Should be in pending list
        pending = list_pending_work_items(db)
        assert len(pending) == 1
        assert pending[0].id == item.id

    def test_work_item_persists_in_db(self, db, scored_app):
        item = create_work_item(
            db,
            application_id="app-1",
            work_type=WorkType.OUTREACH,
            title="Test item",
            instructions="Instructions here.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )

        loaded = get_work_item(db, item.id)
        assert loaded is not None
        assert loaded.title == "Test item"
        assert loaded.instructions == "Instructions here."
        assert loaded.draft_content is None


class TestCompleteWorkItem:
    def test_completes_and_advances_state(self, db, scored_app):
        item = create_work_item(
            db,
            application_id="app-1",
            work_type=WorkType.OUTREACH,
            title="Send outreach",
            instructions="Do it.",
            draft_content="Subject: Hi\n\nHello.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )

        completed = complete_work_item(db, item.id)

        assert completed.status == WorkStatus.COMPLETED
        assert completed.completed_at is not None

        # Application should advance to OUTREACH_SENT
        app = get_application(db, "app-1")
        assert app.status == ApplicationStatus.OUTREACH_SENT

        # Interaction should be recorded
        interactions = list_interactions(db, "app-1")
        assert len(interactions) == 1

        # No pending items left
        assert len(list_pending_work_items(db)) == 0

    def test_raises_for_nonexistent_item(self, db):
        with pytest.raises(ValueError, match="not found"):
            complete_work_item(db, "nonexistent")

    def test_raises_for_already_completed(self, db, scored_app):
        item = create_work_item(
            db,
            application_id="app-1",
            work_type=WorkType.OUTREACH,
            title="Send outreach",
            instructions="Do it.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )
        complete_work_item(db, item.id)

        with pytest.raises(ValueError, match="already COMPLETED"):
            complete_work_item(db, item.id)


class TestSkipWorkItem:
    def test_skips_and_reverts_state(self, db, scored_app):
        item = create_work_item(
            db,
            application_id="app-1",
            work_type=WorkType.OUTREACH,
            title="Send outreach",
            instructions="Do it.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )

        skipped = skip_work_item(db, item.id)

        assert skipped.status == WorkStatus.SKIPPED
        assert skipped.completed_at is not None

        # Application should revert to SCORED
        app = get_application(db, "app-1")
        assert app.status == ApplicationStatus.SCORED

        # No interactions recorded
        interactions = list_interactions(db, "app-1")
        assert len(interactions) == 0

        # No pending items left
        assert len(list_pending_work_items(db)) == 0

    def test_raises_for_nonexistent_item(self, db):
        with pytest.raises(ValueError, match="not found"):
            skip_work_item(db, "nonexistent")

    def test_raises_for_already_skipped(self, db, scored_app):
        item = create_work_item(
            db,
            application_id="app-1",
            work_type=WorkType.OUTREACH,
            title="Send outreach",
            instructions="Do it.",
            target_status=ApplicationStatus.OUTREACH_SENT,
            previous_status=ApplicationStatus.SCORED,
            pending_status=ApplicationStatus.OUTREACH_PENDING,
        )
        skip_work_item(db, item.id)

        with pytest.raises(ValueError, match="already SKIPPED"):
            skip_work_item(db, item.id)
