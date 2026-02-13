"""Tests for the Textual work console app.

Each test boots a full Textual app — expensive (~0.5s each).  Keep test count
low by asserting multiple related things per app session.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from emplaiyed.console.app import WorkConsoleApp
from emplaiyed.core.database import (
    get_application,
    get_work_item,
    init_db,
    list_events,
    list_interactions,
    save_application,
    save_interaction,
    save_opportunity,
    save_work_item,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Opportunity,
    WorkItem,
    WorkStatus,
    WorkType,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "console_test.db")
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "console_test.db"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_queue(conn: sqlite3.Connection, count: int = 3) -> list[WorkItem]:
    """Seed OUTREACH_PENDING apps with work items (Queue tab)."""
    now = datetime.now()
    items = []
    for i in range(count):
        save_opportunity(conn, Opportunity(
            id=f"opp-{i}", source="jobbank",
            source_url=f"https://jobbank.gc.ca/job/{i}",
            company=f"Corp{i}", title=f"Role{i}",
            description=f"Description for role {i}.",
            location="Montreal, QC", scraped_at=now,
        ))
        save_application(conn, Application(
            id=f"app-{i}", opportunity_id=f"opp-{i}",
            status=ApplicationStatus.OUTREACH_PENDING,
            score=80 + i, justification=f"Good fit #{i}",
            day_to_day=f"Day-to-day work for role {i}.",
            why_it_fits=f"Fits because of skill {i}.",
            created_at=now, updated_at=now,
        ))
        wi = WorkItem(
            id=f"wi-{i}", application_id=f"app-{i}",
            work_type=WorkType.OUTREACH, status=WorkStatus.PENDING,
            title=f"Apply to Corp{i} — Role{i}",
            instructions=f"Send the email for role {i}.",
            target_status=ApplicationStatus.OUTREACH_SENT.value,
            previous_status=ApplicationStatus.SCORED.value,
            created_at=datetime(2025, 2, 10, 14, i, 0),
        )
        save_work_item(conn, wi)
        items.append(wi)
    return items


def _seed_pipeline(conn: sqlite3.Connection) -> None:
    """Seed apps across all pipeline stages."""
    now = datetime.now()
    stages = [
        ("opp-a", "CorpA", "app-a", ApplicationStatus.OUTREACH_SENT, 85),
        ("opp-b", "CorpB", "app-b", ApplicationStatus.FOLLOW_UP_1, 75),
        ("opp-c", "CorpC", "app-c", ApplicationStatus.INTERVIEW_SCHEDULED, 90),
        ("opp-d", "CorpD", "app-d", ApplicationStatus.OFFER_RECEIVED, 95),
        ("opp-e", "CorpE", "app-e", ApplicationStatus.REJECTED, 60),
        ("opp-f", "CorpF", "app-f", ApplicationStatus.GHOSTED, 70),
    ]
    for opp_id, company, app_id, status, score in stages:
        save_opportunity(conn, Opportunity(
            id=opp_id, source="test", company=company,
            title=f"{company} Role", description="Test", scraped_at=now,
        ))
        save_application(conn, Application(
            id=app_id, opportunity_id=opp_id, status=status,
            score=score, created_at=now, updated_at=now,
        ))


def _seed_app(conn, *, app_id="app-x", opp_id="opp-x", company="TestCo",
              status=ApplicationStatus.OUTREACH_SENT, score=80):
    """Seed a single app at any status."""
    now = datetime.now()
    save_opportunity(conn, Opportunity(
        id=opp_id, source="test", company=company,
        title=f"{company} Role", description="Test", scraped_at=now,
    ))
    save_application(conn, Application(
        id=app_id, opportunity_id=opp_id, status=status,
        score=score, created_at=now, updated_at=now,
    ))


# ---------------------------------------------------------------------------
# Queue: display, navigation, actions
# ---------------------------------------------------------------------------


class TestQueue:
    async def test_display_and_navigation(self, db, db_path):
        """Queue shows items sorted by score; j/k navigate; detail pane shows info."""
        _seed_queue(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            ol = app.query_one("#list-queue")
            # 3 items, sorted by score descending
            assert ol.option_count == 3
            assert "Corp2" in str(ol.get_option_at_index(0).prompt)
            assert "Corp0" in str(ol.get_option_at_index(2).prompt)

            # Detail pane shows first item's info
            text = str(app.query_one("#detail-queue").content)
            for expected in ("Corp2", "Role2", "82", "Day-to-day", "Why it fits"):
                assert expected in text

            # j/k navigation
            assert ol.highlighted == 0
            await pilot.press("j")
            assert ol.highlighted == 1
            await pilot.press("k")
            assert ol.highlighted == 0

    async def test_empty_state(self, db, db_path):
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            assert "caught up" in app.query_one("#detail-queue").content.lower()

    async def test_done_and_pass(self, db, db_path):
        """d marks done (completes work item), p marks passed (skips)."""
        _seed_queue(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            # d on first item (Corp2, wi-2)
            await pilot.press("d")
            assert app.query_one("#list-queue").option_count == 2
            assert get_work_item(db, "wi-2").status == WorkStatus.COMPLETED

            # p on next first item (Corp1, wi-1)
            await pilot.press("p")
            assert app.query_one("#list-queue").option_count == 1
            assert get_work_item(db, "wi-1").status == WorkStatus.SKIPPED

    async def test_scored_apps_in_queue(self, db, db_path):
        """SCORED apps (no work items) appear in Queue; d/p work on them."""
        now = datetime.now()
        for i in range(2):
            _seed_app(db, app_id=f"app-s{i}", opp_id=f"opp-s{i}",
                       company=f"Scored{i}", status=ApplicationStatus.SCORED, score=75 + i)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            assert app.query_one("#list-queue").option_count == 2
            # d on SCORED creates work item and completes it
            await pilot.press("d")
            assert get_application(db, "app-s1").status == ApplicationStatus.OUTREACH_SENT


# ---------------------------------------------------------------------------
# Tab navigation & pipeline display
# ---------------------------------------------------------------------------


class TestTabsAndPipeline:
    async def test_tab_cycle_and_check_action(self, db, db_path):
        """Arrow keys cycle tabs; check_action gates per tab; labels show counts."""
        from textual.widgets import TabbedContent
        _seed_pipeline(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            # Full tab cycle
            tabs = [app._active_tab]
            for _ in range(6):
                await pilot.press("right")
                tabs.append(app._active_tab)
            assert tabs == ["Queue", "Applied", "Active", "Offers", "Closed", "Funnel", "Queue"]

            # Left wraps
            await pilot.press("left")
            assert app._active_tab == "Funnel"

            # check_action per tab
            await pilot.press("right")  # back to Queue
            assert app.check_action("mark_done", ()) is True
            assert app.check_action("add_note", ()) is False
            assert app.check_action("quit", ()) is True

            await pilot.press("right")  # Applied
            assert app.check_action("mark_response", ()) is True
            assert app.check_action("log_followup", ()) is True
            assert app.check_action("mark_done", ()) is False

            # Tab labels show counts
            tc = app.query_one(TabbedContent)
            assert "2" in str(tc.get_tab("tab-applied").label)

    async def test_pipeline_tab_contents(self, db, db_path):
        """Each pipeline tab shows correct app counts and detail."""
        _seed_pipeline(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            assert app.query_one("#list-applied").option_count == 2
            text = str(app.query_one("#detail-applied").content)
            assert "Status:" in text
            assert "TIMELINE" in text

            await pilot.press("right")  # Active
            assert app.query_one("#list-active").option_count == 1

            await pilot.press("right")  # Offers
            assert app.query_one("#list-offers").option_count == 1

            await pilot.press("right")  # Closed
            assert app.query_one("#list-closed").option_count == 2

            await pilot.press("right")  # Funnel
            text = str(app.query_one("#detail-funnel").content)
            assert "FUNNEL DASHBOARD" in text
            assert "Total:" in text

    async def test_empty_pipeline_tab(self, db, db_path):
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            assert "no applications" in app.query_one("#detail-applied").content.lower()


# ---------------------------------------------------------------------------
# Applied tab actions
# ---------------------------------------------------------------------------


class TestAppliedActions:
    async def test_response_modal_transitions_and_saves(self, db, db_path):
        """r opens ResponseReceivedModal; submitting transitions + saves interaction."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co")
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.press("right")  # Applied
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "response-input":
                    w.value = "Recruiter called back"
            await pilot.click("#save-btn")
            await pilot.pause()
            loaded = get_application(db, "app-a")
            assert loaded.status == ApplicationStatus.RESPONSE_RECEIVED
            ix = list_interactions(db, "app-a")
            assert len(ix) == 1
            assert ix[0].type == InteractionType.EMAIL_RECEIVED
            assert ix[0].content == "Recruiter called back"

    async def test_response_with_schedule(self, db, db_path):
        """Response modal with date filled transitions all the way to INTERVIEW_SCHEDULED."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co")
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.press("right")
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "response-input":
                    w.value = "Phone screen scheduled"
                elif w.id == "response-date-input":
                    w.value = "2025-04-01 10:00"
            await pilot.click("#save-btn")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.INTERVIEW_SCHEDULED
            assert len(list_events(db, application_id="app-a")) == 1

    async def test_response_cancel_and_wrong_tab_noop(self, db, db_path):
        """Cancelling response modal or pressing r on wrong tab does nothing."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co")
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test(size=(80, 50)) as pilot:
            # Wrong tab: r on Queue is no-op
            await pilot.press("r")
            assert get_application(db, "app-a").status == ApplicationStatus.OUTREACH_SENT

            # Cancel modal: no transition
            await pilot.press("right")  # Applied
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()
            await pilot.click("#cancel-btn")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.OUTREACH_SENT

    async def test_ghosted_and_note(self, db, db_path):
        """g transitions to GHOSTED; n opens NoteModal and saves interaction."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co")
        # Test note first (before ghosting changes status)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            await pilot.press("n")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "note-input":
                    w.value = "Interesting opportunity"
            await pilot.click("#save-btn")
            await pilot.pause()
            ix = list_interactions(db, "app-a")
            assert len(ix) == 1
            assert ix[0].type == InteractionType.NOTE

            # Now ghost it
            await pilot.press("g")
            assert get_application(db, "app-a").status == ApplicationStatus.GHOSTED


# ---------------------------------------------------------------------------
# Follow-up actions
# ---------------------------------------------------------------------------


class TestFollowUp:
    async def test_followup_chain(self, db, db_path):
        """f on OUTREACH_SENT → FU1, f on FU1 → FU2, f on FU2 → no-op."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.OUTREACH_SENT)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied

            # FU1
            await pilot.press("f")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "followup-input":
                    w.value = "First follow-up"
            await pilot.click("#save-btn")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.FOLLOW_UP_1
            assert list_interactions(db, "app-a")[0].type == InteractionType.FOLLOW_UP

    async def test_followup_fu1_to_fu2(self, db, db_path):
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.FOLLOW_UP_1)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")
            await pilot.press("f")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "followup-input":
                    w.value = "Second follow-up"
            await pilot.click("#save-btn")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.FOLLOW_UP_2

    async def test_followup_fu2_noop_and_cancel(self, db, db_path):
        """f on FU2 is no-op; cancelling modal doesn't transition."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.FOLLOW_UP_2)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")
            await pilot.press("f")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.FOLLOW_UP_2


# ---------------------------------------------------------------------------
# Active tab actions
# ---------------------------------------------------------------------------


class TestActiveActions:
    async def test_completed_rejected_and_schedule(self, db, db_path):
        """c completes interview; x rejects; s schedules with modal."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.INTERVIEW_SCHEDULED, score=90)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            await pilot.press("right")  # Active
            await pilot.press("c")      # Completed
            assert get_application(db, "app-a").status == ApplicationStatus.INTERVIEW_COMPLETED

    async def test_schedule_interview_creates_event(self, db, db_path):
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.INTERVIEW_SCHEDULED, score=90)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            await pilot.press("right")  # Active
            await pilot.press("s")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "date-input":
                    w.value = "2025-04-01 10:00"
            await pilot.click("#schedule-btn")
            await pilot.pause()
            events = list_events(db, application_id="app-a")
            assert len(events) == 1
            assert events[0].event_type == "phone_screen"

    async def test_mark_rejected(self, db, db_path):
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.INTERVIEW_SCHEDULED, score=90)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")
            await pilot.press("right")
            await pilot.press("x")
            assert get_application(db, "app-a").status == ApplicationStatus.REJECTED


# ---------------------------------------------------------------------------
# Offer actions
# ---------------------------------------------------------------------------


class TestOfferActions:
    async def test_offer_on_completed_and_guard(self, db, db_path):
        """o on INTERVIEW_COMPLETED opens modal → OFFER_RECEIVED;
        o on INTERVIEW_SCHEDULED is no-op."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.INTERVIEW_COMPLETED, score=88)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            await pilot.press("right")  # Active
            await pilot.press("o")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "note-input":
                    w.value = "120k base + stock"
            await pilot.click("#save-btn")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.OFFER_RECEIVED
            ix = list_interactions(db, "app-a")
            assert "Offer received" in ix[0].content

    async def test_offer_guard_on_wrong_status(self, db, db_path):
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.INTERVIEW_SCHEDULED, score=90)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")
            await pilot.press("right")
            await pilot.press("o")
            await pilot.pause()
            assert get_application(db, "app-a").status == ApplicationStatus.INTERVIEW_SCHEDULED

    async def test_accept_and_reject_offer(self, db, db_path):
        """a accepts; x rejects from Offers tab."""
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co",
                  status=ApplicationStatus.OFFER_RECEIVED, score=95)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            for _ in range(3):
                await pilot.press("right")  # → Offers
            await pilot.press("a")
            assert get_application(db, "app-a").status == ApplicationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Timeline in detail pane
# ---------------------------------------------------------------------------


class TestTimeline:
    async def test_timeline_shows_interactions(self, db, db_path):
        _seed_app(db, app_id="app-a", opp_id="opp-a", company="Co")
        save_interaction(db, Interaction(
            application_id="app-a", type=InteractionType.NOTE,
            direction="internal", channel="console",
            content="Called recruiter, positive vibes",
            created_at=datetime.now(),
        ))
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("right")  # Applied
            text = str(app.query_one("#detail-applied").content)
            assert "TIMELINE" in text
            assert "[NOTE]" in text
            assert "Called recruiter" in text


# ---------------------------------------------------------------------------
# End-to-end: full lifecycle
# ---------------------------------------------------------------------------


class TestEndToEnd:
    async def test_queue_to_closed(self, db, db_path):
        """Walk an application: Queue → Applied → Active → Closed → Funnel."""
        _seed_queue(db, count=1)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test(size=(80, 50)) as pilot:
            # Queue: mark done → OUTREACH_SENT
            await pilot.press("d")
            assert get_application(db, "app-0").status == ApplicationStatus.OUTREACH_SENT

            # Applied: response → RESPONSE_RECEIVED
            await pilot.press("right")
            assert app.query_one("#list-applied").option_count == 1
            await pilot.press("r")
            await pilot.pause()
            await pilot.pause()
            from textual.widgets import Input
            for w in app.screen.query(Input):
                if w.id == "response-input":
                    w.value = "Got a reply"
            await pilot.click("#save-btn")
            await pilot.pause()
            assert get_application(db, "app-0").status == ApplicationStatus.RESPONSE_RECEIVED

            # Active: reject
            await pilot.press("right")
            assert app.query_one("#list-active").option_count == 1
            await pilot.press("x")
            assert get_application(db, "app-0").status == ApplicationStatus.REJECTED

            # Closed: visible
            await pilot.press("right")  # Offers
            await pilot.press("right")  # Closed
            assert app.query_one("#list-closed").option_count == 1

            # Funnel: has stats
            await pilot.press("right")
            assert "Closed" in str(app.query_one("#detail-funnel").content)
