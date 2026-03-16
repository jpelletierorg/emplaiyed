"""Tests for the search modal screen."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from emplaiyed.console.search_modal import SearchModal, _format_result
from emplaiyed.core.database import (
    init_db,
    rebuild_search_index,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
)


class ModalTestApp(App):
    """Minimal app shell for testing the search modal."""

    def compose(self) -> ComposeResult:
        yield Static("Host app")


def _seed_db(db: sqlite3.Connection) -> None:
    """Insert test opportunities and applications."""
    now = datetime(2025, 6, 1, 10, 0, 0)
    opps = [
        Opportunity(
            id="opp-alpha",
            source="jobbank",
            company="AlphaCorp",
            title="ML Engineer",
            description="Build ML models with Python and PyTorch.",
            location="Montreal, QC",
            scraped_at=now,
        ),
        Opportunity(
            id="opp-beta",
            source="indeed",
            company="BetaWorks",
            title="DevOps Lead",
            description="Kubernetes, Terraform, AWS infrastructure.",
            location="Toronto, ON",
            scraped_at=now,
        ),
        Opportunity(
            id="opp-gamma",
            source="manual",
            company="GammaTech",
            title="Data Scientist",
            description="Statistical modelling, R, Python, dashboards.",
            location="Ottawa, ON",
            scraped_at=now,
        ),
    ]
    for opp in opps:
        save_opportunity(db, opp)

    save_application(
        db,
        Application(
            id="app-alpha",
            opportunity_id="opp-alpha",
            status=ApplicationStatus.SCORED,
            score=85,
            created_at=now,
            updated_at=now,
        ),
    )
    save_application(
        db,
        Application(
            id="app-beta",
            opportunity_id="opp-beta",
            status=ApplicationStatus.OUTREACH_SENT,
            score=72,
            created_at=now,
            updated_at=now,
        ),
    )
    # opp-gamma has no application

    rebuild_search_index(db)


# ---------------------------------------------------------------------------
# Unit tests for _format_result
# ---------------------------------------------------------------------------


class TestFormatResult:
    def test_with_app_and_score(self) -> None:
        opp = Opportunity(
            id="o1",
            source="test",
            company="Acme",
            title="Dev",
            description="D",
            location="MTL",
            scraped_at=datetime(2025, 1, 1),
        )
        app = Application(
            id="a1",
            opportunity_id="o1",
            status=ApplicationStatus.SCORED,
            score=80,
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        label = _format_result(opp, app)
        assert "80" in label
        assert "Acme" in label
        assert "Dev" in label
        assert "MTL" in label
        assert "SCORED" in label

    def test_without_app(self) -> None:
        opp = Opportunity(
            id="o2",
            source="test",
            company="BigCo",
            title="Eng",
            description="D",
            scraped_at=datetime(2025, 1, 1),
        )
        label = _format_result(opp, None)
        assert "BigCo" in label
        assert "no app" in label


# ---------------------------------------------------------------------------
# Textual integration tests
# ---------------------------------------------------------------------------


class TestSearchModalIntegration:
    async def test_escape_dismisses(self, tmp_path: Path) -> None:
        db = init_db(tmp_path / "test.db")
        dismissed = []

        def on_dismiss(result):
            dismissed.append(result)

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = SearchModal(db)
            app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert dismissed == [None]
        db.close()

    async def test_search_populates_results(self, tmp_path: Path) -> None:
        db = init_db(tmp_path / "test.db")
        _seed_db(db)

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = SearchModal(db)
            app.push_screen(modal)
            await pilot.pause()
            await pilot.pause()

            inp = app.screen.query_one("#search-input", Input)
            inp.value = "AlphaCorp"
            inp.focus()
            await pilot.press("enter")
            await pilot.pause()

            results = app.screen.query_one("#search-results", OptionList)
            assert results.option_count >= 1
            status = app.screen.query_one("#search-status", Static)
            assert "result" in status.content.lower()

        db.close()

    async def test_no_results_shows_message(self, tmp_path: Path) -> None:
        db = init_db(tmp_path / "test.db")
        _seed_db(db)

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = SearchModal(db)
            app.push_screen(modal)
            await pilot.pause()
            await pilot.pause()

            inp = app.screen.query_one("#search-input", Input)
            inp.value = "zzzznonexistent"
            inp.focus()
            await pilot.press("enter")
            await pilot.pause()

            status = app.screen.query_one("#search-status", Static)
            assert "no results" in status.content.lower()

        db.close()

    async def test_select_result_with_app_dismisses(self, tmp_path: Path) -> None:
        db = init_db(tmp_path / "test.db")
        _seed_db(db)
        dismissed = []

        def on_dismiss(result):
            dismissed.append(result)

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = SearchModal(db)
            app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()
            await pilot.pause()

            inp = app.screen.query_one("#search-input", Input)
            inp.value = "DevOps"
            inp.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Select the first (and likely only) result
            results_list = app.screen.query_one("#search-results", OptionList)
            results_list.focus()
            await pilot.press("enter")
            await pilot.pause()

        assert len(dismissed) == 1
        assert dismissed[0] == "app-beta"
        db.close()

    async def test_select_result_without_app_shows_warning(
        self, tmp_path: Path
    ) -> None:
        db = init_db(tmp_path / "test.db")
        _seed_db(db)

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = SearchModal(db)
            app.push_screen(modal)
            await pilot.pause()
            await pilot.pause()

            inp = app.screen.query_one("#search-input", Input)
            inp.value = "GammaTech"
            inp.focus()
            await pilot.press("enter")
            await pilot.pause()

            results_list = app.screen.query_one("#search-results", OptionList)
            results_list.focus()
            await pilot.press("enter")
            await pilot.pause()

            # Should stay open (not dismissed), with a warning
            status = app.screen.query_one("#search-status", Static)
            assert "no application" in status.content.lower()

        db.close()
