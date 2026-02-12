"""Tests for emplaiyed.followup.agent — follow-up detection and drafting."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.database import (
    init_db,
    list_applications,
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
from emplaiyed.core.database import get_work_item, list_pending_work_items
from emplaiyed.followup.agent import (
    FollowUpDraft,
    draft_followup,
    enqueue_followup,
    find_stale_applications,
    send_followup,
)


def _test_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python"],
    )


def _test_opportunity() -> Opportunity:
    return Opportunity(
        source="jobbank",
        company="Stale Corp",
        title="Developer",
        description="A job.",
        scraped_at=datetime.now(),
    )


class TestFindStaleApplications:
    def test_finds_stale_outreach(self, tmp_path: Path):
        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity()
        save_opportunity(db_conn, opp)

        # Create an application updated 7 days ago
        old_time = datetime.now() - timedelta(days=7)
        app = Application(
            opportunity_id=opp.id,
            status=ApplicationStatus.OUTREACH_SENT,
            created_at=old_time,
            updated_at=old_time,
        )
        save_application(db_conn, app)

        stale = find_stale_applications(db_conn, stale_days=5)
        assert len(stale) == 1
        assert stale[0][1] == "FOLLOW_UP_1"
        assert stale[0][3] >= 7
        db_conn.close()

    def test_ignores_recent_applications(self, tmp_path: Path):
        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity()
        save_opportunity(db_conn, opp)

        now = datetime.now()
        app = Application(
            opportunity_id=opp.id,
            status=ApplicationStatus.OUTREACH_SENT,
            created_at=now,
            updated_at=now,
        )
        save_application(db_conn, app)

        stale = find_stale_applications(db_conn, stale_days=5)
        assert len(stale) == 0
        db_conn.close()


class TestDraftFollowup:
    async def test_returns_draft(self):
        result = await draft_followup(
            _test_profile(),
            _test_opportunity(),
            followup_number=1,
            days_since=7,
            _model_override=TestModel(),
        )
        assert isinstance(result, FollowUpDraft)
        assert result.subject
        assert result.body


class TestSendFollowup:
    def test_records_and_transitions(self, tmp_path: Path):
        """send_followup does two-step: OUTREACH_SENT→FOLLOW_UP_PENDING→FOLLOW_UP_1."""
        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity()
        save_opportunity(db_conn, opp)

        old_time = datetime.now() - timedelta(days=7)
        app = Application(
            opportunity_id=opp.id,
            status=ApplicationStatus.OUTREACH_SENT,
            created_at=old_time,
            updated_at=old_time,
        )
        save_application(db_conn, app)

        draft = FollowUpDraft(subject="Following up", body="Just checking in.")
        send_followup(db_conn, app.id, draft, ApplicationStatus.FOLLOW_UP_1)

        interactions = list_interactions(db_conn, app.id)
        assert len(interactions) == 1

        apps = list_applications(db_conn)
        assert apps[0].status == ApplicationStatus.FOLLOW_UP_1
        db_conn.close()


class TestEnqueueFollowup:
    def test_creates_work_item_and_transitions_to_pending(self, tmp_path: Path):
        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity()
        save_opportunity(db_conn, opp)

        old_time = datetime.now() - timedelta(days=7)
        app = Application(
            opportunity_id=opp.id,
            status=ApplicationStatus.OUTREACH_SENT,
            created_at=old_time,
            updated_at=old_time,
        )
        save_application(db_conn, app)

        draft = FollowUpDraft(subject="Following up", body="Just checking in.")
        item = enqueue_followup(
            db_conn, app.id, opp, draft,
            target_status=ApplicationStatus.FOLLOW_UP_1,
            previous_status=ApplicationStatus.OUTREACH_SENT,
            followup_number=1,
        )

        # Application should be in FOLLOW_UP_PENDING
        apps = list_applications(db_conn)
        assert apps[0].status == ApplicationStatus.FOLLOW_UP_PENDING

        # Work item should exist
        loaded = get_work_item(db_conn, item.id)
        assert loaded is not None
        assert loaded.target_status == "FOLLOW_UP_1"
        assert loaded.previous_status == "OUTREACH_SENT"
        assert "Following up" in loaded.draft_content

        pending = list_pending_work_items(db_conn)
        assert len(pending) == 1

        db_conn.close()
