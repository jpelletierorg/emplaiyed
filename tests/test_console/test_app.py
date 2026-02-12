"""Tests for the Textual work console app."""

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
    list_pending_work_items,
    save_application,
    save_opportunity,
    save_work_item,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
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


def _seed_data(conn: sqlite3.Connection, count: int = 3) -> list[WorkItem]:
    """Seed DB with opportunities, applications, and work items."""
    now = datetime.now()
    items = []
    for i in range(count):
        opp = Opportunity(
            id=f"opp-{i}",
            source="jobbank",
            source_url=f"https://jobbank.gc.ca/job/{i}",
            company=f"Corp{i}",
            title=f"Role{i}",
            description=f"Description for role {i}.",
            location="Montreal, QC",
            scraped_at=now,
        )
        save_opportunity(conn, opp)

        app = Application(
            id=f"app-{i}",
            opportunity_id=f"opp-{i}",
            status=ApplicationStatus.OUTREACH_PENDING,
            score=80 + i,
            justification=f"Good fit #{i}",
            day_to_day=f"Day-to-day work for role {i}.",
            why_it_fits=f"Fits because of skill {i}.",
            created_at=now,
            updated_at=now,
        )
        save_application(conn, app)

        wi = WorkItem(
            id=f"wi-{i}",
            application_id=f"app-{i}",
            work_type=WorkType.OUTREACH,
            status=WorkStatus.PENDING,
            title=f"Apply to Corp{i} — Role{i}",
            instructions=f"Send the email for role {i}.",
            target_status=ApplicationStatus.OUTREACH_SENT.value,
            previous_status=ApplicationStatus.SCORED.value,
            created_at=datetime(2025, 2, 10, 14, i, 0),
        )
        save_work_item(conn, wi)
        items.append(wi)
    return items


class TestConsoleAppLaunch:
    async def test_app_shows_items(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 3

    async def test_empty_state_message(self, db, db_path):
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            detail = app.query_one("#detail-pane")
            assert "caught up" in detail.content.lower()

    async def test_items_ordered_by_score_descending(self, db, db_path):
        """Highest-scored items should appear first in the list."""
        _seed_data(db)  # scores are 80, 81, 82
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            option_list = app.query_one("#item-list")
            # Corp2 has score 82 (highest), should be first
            first_label = str(option_list.get_option_at_index(0).prompt)
            assert "Corp2" in first_label
            last_label = str(option_list.get_option_at_index(2).prompt)
            assert "Corp0" in last_label


class TestConsoleNavigation:
    async def test_j_moves_down(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            option_list = app.query_one("#item-list")
            assert option_list.highlighted == 0
            await pilot.press("j")
            assert option_list.highlighted == 1

    async def test_k_moves_up(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("j")  # go to 1
            await pilot.press("k")  # back to 0
            option_list = app.query_one("#item-list")
            assert option_list.highlighted == 0


class TestConsoleActions:
    async def test_d_marks_done_and_removes(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            # First item is wi-2 (Corp2, score 82 — highest)
            await pilot.press("d")
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 2
            loaded = get_work_item(db, "wi-2")
            assert loaded.status == WorkStatus.COMPLETED

    async def test_p_marks_passed_and_removes(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            # First item is wi-2 (Corp2, score 82 — highest)
            await pilot.press("p")
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 2
            loaded = get_work_item(db, "wi-2")
            assert loaded.status == WorkStatus.SKIPPED


class TestConsoleDetailPane:
    async def test_detail_shows_opportunity_info(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            detail = app.query_one("#detail-pane")
            text = str(detail.content)
            # First item is Corp2 (score 82 — highest)
            assert "Corp2" in text
            assert "Role2" in text

    async def test_detail_shows_score(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            detail = app.query_one("#detail-pane")
            text = str(detail.content)
            assert "82" in text

    async def test_detail_shows_day_to_day(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            detail = app.query_one("#detail-pane")
            text = str(detail.content)
            assert "Day-to-day" in text

    async def test_detail_shows_why_it_fits(self, db, db_path):
        _seed_data(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            detail = app.query_one("#detail-pane")
            text = str(detail.content)
            assert "Why it fits" in text


def _seed_with_backlog(conn: sqlite3.Connection) -> None:
    """Seed 1 work item + 2 scored-but-no-work-item apps (the backlog)."""
    now = datetime.now()

    # Active item with work item
    opp0 = Opportunity(
        id="opp-active", source="jobbank", company="ActiveCorp",
        title="Active Role", description="D", scraped_at=now,
    )
    save_opportunity(conn, opp0)
    app0 = Application(
        id="app-active", opportunity_id="opp-active",
        status=ApplicationStatus.OUTREACH_PENDING,
        score=90, justification="Great", day_to_day="Build stuff.",
        why_it_fits="Perfect match.", created_at=now, updated_at=now,
    )
    save_application(conn, app0)
    wi = WorkItem(
        id="wi-active", application_id="app-active",
        work_type=WorkType.OUTREACH, status=WorkStatus.PENDING,
        title="Apply to ActiveCorp — Active Role",
        instructions="Send the email.",
        target_status=ApplicationStatus.OUTREACH_SENT.value,
        previous_status=ApplicationStatus.SCORED.value,
        created_at=now,
    )
    save_work_item(conn, wi)

    # Backlog: scored but no work items yet
    for i, (score, company) in enumerate([(85, "BacklogHigh"), (70, "BacklogLow")]):
        opp = Opportunity(
            id=f"opp-backlog-{i}", source="jobbank", company=company,
            title=f"Backlog Role {i}", description="D", scraped_at=now,
        )
        save_opportunity(conn, opp)
        app = Application(
            id=f"app-backlog-{i}", opportunity_id=f"opp-backlog-{i}",
            status=ApplicationStatus.SCORED,
            score=score, justification=f"Fit #{i}",
            day_to_day=f"Daily for {company}.",
            why_it_fits=f"Fits for {company}.",
            created_at=now, updated_at=now,
        )
        save_application(conn, app)


class TestConsolePromotion:
    async def test_done_promotes_next_scored(self, db, db_path):
        _seed_with_backlog(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            # Start with 1 pending item
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 1

            # Complete it — should promote highest scored backlog item
            await pilot.press("d")
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 1  # replaced, not empty

            # The promoted item should be BacklogHigh (score=85 > 70)
            promoted_app = get_application(db, "app-backlog-0")
            assert promoted_app.status == ApplicationStatus.OUTREACH_PENDING

    async def test_pass_promotes_next_scored(self, db, db_path):
        _seed_with_backlog(db)
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 1

            await pilot.press("p")
            option_list = app.query_one("#item-list")
            assert option_list.option_count == 1

            promoted_app = get_application(db, "app-backlog-0")
            assert promoted_app.status == ApplicationStatus.OUTREACH_PENDING

    async def test_no_backlog_shows_empty(self, db, db_path):
        """When all scored items are exhausted, show empty state."""
        _seed_data(db, count=1)  # 1 item, no backlog
        app = WorkConsoleApp(db_path=db_path)
        async with app.run_test() as pilot:
            await pilot.press("d")
            detail = app.query_one("#detail-pane")
            assert "caught up" in detail.content.lower()
