"""End-to-end happy path test — exercises the full pipeline with TestModel.

This test proves the complete flow works:
scan → score → outreach → followup → schedule → prep → negotiate → accept
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.database import (
    init_db,
    get_application,
    get_opportunity,
    list_applications,
    list_interactions,
    list_offers,
    list_pending_work_items,
    list_upcoming_events,
    save_application,
    save_event,
    save_offer,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Aspirations,
    Employment,
    Offer,
    OfferStatus,
    Opportunity,
    Profile,
    ScheduledEvent,
)
from emplaiyed.followup.agent import (
    find_stale_applications,
    draft_followup,
    enqueue_followup,
    send_followup,
)
from emplaiyed.generation.pipeline import generate_assets
from emplaiyed.negotiation.advisor import generate_negotiation
from emplaiyed.outreach.drafter import draft_outreach, enqueue_outreach, send_outreach
from emplaiyed.prep.agent import generate_prep
from emplaiyed.scoring.scorer import score_opportunities
from emplaiyed.tracker.state_machine import transition
from emplaiyed.work.queue import complete_work_item


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Jonathan Pelletier",
        email="jonathan@example.com",
        skills=["Python", "AWS", "Docker", "Kubernetes", "SQL"],
        employment_history=[
            Employment(
                company="Croesus",
                title="Lead Cloud Architect",
                start_date=None,
            ),
        ],
        aspirations=Aspirations(
            target_roles=["Applied AI Engineer"],
            salary_minimum=70000,
            salary_target=130000,
            geographic_preferences=["Montreal"],
            work_arrangement=["remote", "hybrid"],
        ),
    )


@pytest.fixture
def db(tmp_path: Path):
    conn = init_db(tmp_path / "happy_path.db")
    yield conn
    conn.close()


@pytest.fixture
def opportunities() -> list[Opportunity]:
    """Simulated scraped opportunities."""
    now = datetime.now()
    return [
        Opportunity(
            source="jobbank",
            company="Coveo",
            title="Applied ML Engineer",
            description="Build production ML pipelines for search relevance. "
            "Python, Kubernetes, TensorFlow. Quebec City HQ, remote OK.",
            location="Québec, QC",
            salary_min=110000,
            salary_max=140000,
            scraped_at=now,
        ),
        Opportunity(
            source="jobbank",
            company="Bell Canada",
            title="Technical Architect - Software",
            description="Lead architecture for cloud-native microservices. "
            "Java, Python, AWS. Montreal.",
            location="Montréal, QC",
            salary_min=90000,
            salary_max=150000,
            scraped_at=now,
        ),
        Opportunity(
            source="jobbank",
            company="Random Staffing Inc",
            title="Junior Data Entry Clerk",
            description="Enter data into spreadsheets. No experience required.",
            location="Toronto, ON",
            salary_min=30000,
            salary_max=35000,
            scraped_at=now,
        ),
    ]


class TestHappyPath:
    """Full pipeline: scan → score → outreach → followup → schedule → prep → negotiate → accept."""

    async def test_full_pipeline(self, profile, db, opportunities):
        model = TestModel()

        # ---- Step 1: Save opportunities (simulating scrape_and_persist) ----
        for opp in opportunities:
            save_opportunity(db, opp)

        # ---- Step 2: Score opportunities ----
        scored = await score_opportunities(
            profile, opportunities, db_conn=db, _model_override=model
        )
        assert len(scored) == 3
        # All should have Application records in SCORED status
        apps = list_applications(db, status=ApplicationStatus.SCORED)
        assert len(apps) == 3

        # ---- Step 3: Outreach via work queue ----
        # Pick the top scored opportunity
        top = scored[0]
        top_app = next(
            a for a in apps if a.opportunity_id == top.opportunity.id
        )

        draft = await draft_outreach(profile, top.opportunity, _model_override=model)
        assert draft.subject
        assert draft.body

        # Enqueue → assert PENDING
        work_item = enqueue_outreach(db, top_app.id, top.opportunity, draft)
        updated_app = get_application(db, top_app.id)
        assert updated_app.status == ApplicationStatus.OUTREACH_PENDING

        # Complete → assert OUTREACH_SENT
        complete_work_item(db, work_item.id)
        updated_app = get_application(db, top_app.id)
        assert updated_app.status == ApplicationStatus.OUTREACH_SENT

        # Check interaction was recorded
        interactions = list_interactions(db, top_app.id)
        assert len(interactions) == 1

        # ---- Step 4: Follow-up via work queue (simulate time passing) ----
        old_time = datetime.now() - timedelta(days=7)
        backdated = updated_app.model_copy(update={"updated_at": old_time})
        save_application(db, backdated)

        stale = find_stale_applications(db, stale_days=5)
        assert len(stale) >= 1

        fu_draft = await draft_followup(
            profile, top.opportunity, 1, 7, _model_override=model
        )

        # Enqueue follow-up → assert FOLLOW_UP_PENDING
        fu_item = enqueue_followup(
            db, top_app.id, top.opportunity, fu_draft,
            target_status=ApplicationStatus.FOLLOW_UP_1,
            previous_status=ApplicationStatus.OUTREACH_SENT,
            followup_number=1,
        )
        updated_app = get_application(db, top_app.id)
        assert updated_app.status == ApplicationStatus.FOLLOW_UP_PENDING

        # Complete → assert FOLLOW_UP_1
        complete_work_item(db, fu_item.id)
        updated_app = get_application(db, top_app.id)
        assert updated_app.status == ApplicationStatus.FOLLOW_UP_1

        # ---- Step 5: Response received → Interview scheduled ----
        transition(db, top_app.id, ApplicationStatus.RESPONSE_RECEIVED)
        transition(db, top_app.id, ApplicationStatus.INTERVIEW_SCHEDULED)

        # Schedule the interview
        event = ScheduledEvent(
            application_id=top_app.id,
            event_type="phone_screen",
            scheduled_date=datetime.now() + timedelta(days=3),
            notes="With Sarah Chen, Talent Acquisition",
            created_at=datetime.now(),
        )
        save_event(db, event)
        upcoming = list_upcoming_events(db)
        assert len(upcoming) == 1

        # ---- Step 6: Prep ----
        sheet = await generate_prep(profile, top.opportunity, _model_override=model)
        assert sheet.company_summary
        assert sheet.salary_notes

        # ---- Step 7: Interview completed → Offer received ----
        transition(db, top_app.id, ApplicationStatus.INTERVIEW_COMPLETED)
        transition(db, top_app.id, ApplicationStatus.OFFER_RECEIVED)

        # Record the offer
        offer = Offer(
            application_id=top_app.id,
            salary=115000,
            status=OfferStatus.PENDING,
            created_at=datetime.now(),
        )
        save_offer(db, offer)

        offers = list_offers(db, application_id=top_app.id)
        assert len(offers) == 1
        assert offers[0].salary == 115000

        # ---- Step 8: Negotiate (backward compat path for simplicity) ----
        strategy = await generate_negotiation(
            profile, top.opportunity, offer, _model_override=model
        )
        assert strategy.analysis
        assert strategy.recommended_counter >= 0  # TestModel returns 0

        transition(db, top_app.id, ApplicationStatus.NEGOTIATING)

        # Counter-offer accepted → new offer
        transition(db, top_app.id, ApplicationStatus.OFFER_RECEIVED)
        updated_offer = offer.model_copy(update={"salary": 122000})
        save_offer(db, updated_offer)

        # ---- Step 9: Accept (backward compat path) ----
        transition(db, top_app.id, ApplicationStatus.ACCEPTED)
        final_app = get_application(db, top_app.id)
        assert final_app.status == ApplicationStatus.ACCEPTED

        # ---- Verify final state ----
        all_apps = list_applications(db)
        assert len(all_apps) == 3  # 3 opportunities scored

        # The accepted app should be in ACCEPTED
        accepted = [a for a in all_apps if a.status == ApplicationStatus.ACCEPTED]
        assert len(accepted) == 1

        # The other two should still be in SCORED
        scored_apps = [a for a in all_apps if a.status == ApplicationStatus.SCORED]
        assert len(scored_apps) == 2

        # Interactions recorded for the accepted app
        all_interactions = list_interactions(db, top_app.id)
        assert len(all_interactions) == 2  # outreach + follow-up

    async def test_asset_generation(self, profile, db, opportunities, tmp_path):
        """Asset generation creates CV + letter files."""
        model = TestModel()

        # Save opportunity
        save_opportunity(db, opportunities[0])

        # Generate assets
        paths = await generate_assets(
            profile, opportunities[0], "test-app",
            _model_override=model,
            asset_dir=tmp_path / "assets" / "test-app",
        )

        assert paths.cv_md.exists()
        assert paths.cv_pdf.exists()
        assert paths.letter_md.exists()
        assert paths.letter_pdf.exists()

        # CV markdown has content
        cv_text = paths.cv_md.read_text()
        assert len(cv_text) > 0

        # PDF files are valid
        assert paths.cv_pdf.read_bytes()[:5] == b"%PDF-"
        assert paths.letter_pdf.read_bytes()[:5] == b"%PDF-"

    async def test_passed_state(self, profile, db, opportunities):
        """SCORED applications can be marked as PASSED (terminal)."""
        model = TestModel()

        for opp in opportunities:
            save_opportunity(db, opp)

        scored = await score_opportunities(
            profile, opportunities, db_conn=db, _model_override=model
        )
        apps = list_applications(db, status=ApplicationStatus.SCORED)
        assert len(apps) == 3

        # Pass the lowest scored opportunity
        low_app = apps[-1]
        transition(db, low_app.id, ApplicationStatus.PASSED)

        passed_app = get_application(db, low_app.id)
        assert passed_app.status == ApplicationStatus.PASSED

        # Verify remaining apps still SCORED
        still_scored = list_applications(db, status=ApplicationStatus.SCORED)
        assert len(still_scored) == 2
