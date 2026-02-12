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
from emplaiyed.outreach.drafter import OutreachDraft, draft_outreach, send_outreach


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

        # Check application transitioned to OUTREACH_SENT
        apps = list_applications(db_conn)
        assert apps[0].status == ApplicationStatus.OUTREACH_SENT

        db_conn.close()
