"""Tests for emplaiyed.outreach.drafter — outreach email drafting."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.database import init_db, list_applications, list_interactions, save_application
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Aspirations,
    Employment,
    Opportunity,
    Profile,
)
from emplaiyed.core.database import get_work_item, list_pending_work_items
from emplaiyed.outreach.drafter import OutreachDraft, draft_outreach, enqueue_outreach, send_outreach


def _test_profile() -> Profile:
    return Profile(
        name="Jonathan Test",
        email="test@example.com",
        skills=["Python", "AWS", "Docker"],
        employment_history=[
            Employment(
                company="Previous Corp",
                title="Lead Cloud Architect",
                start_date=None,
            )
        ],
        aspirations=Aspirations(target_roles=["Software Engineer"]),
    )


def _test_opportunity() -> Opportunity:
    return Opportunity(
        source="jobbank",
        company="Target Inc",
        title="Software Developer",
        description="Looking for a Python developer with cloud experience.",
        location="Montreal, QC",
        scraped_at=datetime.now(),
    )


class TestDraftOutreach:
    async def test_returns_outreach_draft(self):
        result = await draft_outreach(
            _test_profile(),
            _test_opportunity(),
            _model_override=TestModel(),
        )
        assert isinstance(result, OutreachDraft)
        assert result.subject  # not empty
        assert result.body  # not empty


class TestSendOutreach:
    def test_records_interaction_and_transitions(self, tmp_path: Path):
        """send_outreach does two-step: SCORED→OUTREACH_PENDING→OUTREACH_SENT."""
        from emplaiyed.core.database import save_opportunity

        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity()
        save_opportunity(db_conn, opp)  # FK constraint

        # Create an application in SCORED state
        now = datetime.now()
        app = Application(
            opportunity_id=opp.id,
            status=ApplicationStatus.SCORED,
            created_at=now,
            updated_at=now,
        )
        save_application(db_conn, app)

        draft = OutreachDraft(
            subject="Application — Software Developer",
            body="Dear Hiring Team, I'd love to join your team.",
        )

        send_outreach(db_conn, app.id, draft)

        # Check interaction was recorded
        interactions = list_interactions(db_conn, app.id)
        assert len(interactions) == 1
        assert "Application — Software Developer" in interactions[0].content

        # Check application transitioned to OUTREACH_SENT (via OUTREACH_PENDING)
        apps = list_applications(db_conn)
        assert apps[0].status == ApplicationStatus.OUTREACH_SENT

        db_conn.close()


class TestEnqueueOutreach:
    def test_creates_work_item_and_transitions_to_pending(self, tmp_path: Path):
        from emplaiyed.core.database import save_opportunity

        db_conn = init_db(tmp_path / "test.db")
        opp = _test_opportunity()
        save_opportunity(db_conn, opp)

        now = datetime.now()
        app = Application(
            opportunity_id=opp.id,
            status=ApplicationStatus.SCORED,
            created_at=now,
            updated_at=now,
        )
        save_application(db_conn, app)

        draft = OutreachDraft(
            subject="Application — Software Developer",
            body="Dear Hiring Team, I'd love to join your team.",
        )

        item = enqueue_outreach(db_conn, app.id, opp, draft)

        # Application should be in OUTREACH_PENDING
        apps = list_applications(db_conn)
        assert apps[0].status == ApplicationStatus.OUTREACH_PENDING

        # Work item should exist and be PENDING
        loaded = get_work_item(db_conn, item.id)
        assert loaded is not None
        assert loaded.target_status == "OUTREACH_SENT"
        assert loaded.previous_status == "SCORED"
        assert loaded.draft_content is not None
        assert "Application — Software Developer" in loaded.draft_content

        # Should appear in pending list
        pending = list_pending_work_items(db_conn)
        assert len(pending) == 1

        db_conn.close()
