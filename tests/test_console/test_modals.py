"""Tests for modal screens (NoteModal, ScheduleInterviewModal)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from emplaiyed.console.modals import NoteModal, ScheduleInterviewModal


class ModalTestApp(App):
    """Minimal app shell for testing modal screens."""

    def compose(self) -> ComposeResult:
        yield Static("Host app")


async def _push_and_wait(app, pilot, modal_cls, callback):
    """Push a modal and wait for it to mount."""
    app.push_screen(modal_cls(), callback=callback)
    # Need multiple pauses for screen mounting + composing
    await pilot.pause()
    await pilot.pause()


class TestNoteModal:
    async def test_save_returns_text(self):
        result = None

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, NoteModal, capture)
            # Type into the focused input
            for widget in app.screen.query(Input):
                if widget.id == "note-input":
                    widget.value = "This is a test note"
            await pilot.click("#save-btn")
            await pilot.pause()
            assert result == "This is a test note"

    async def test_cancel_returns_none(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, NoteModal, capture)
            await pilot.click("#cancel-btn")
            await pilot.pause()
            assert result is None

    async def test_escape_returns_none(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, NoteModal, capture)
            await pilot.press("escape")
            await pilot.pause()
            assert result is None

    async def test_empty_input_not_submitted(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, NoteModal, capture)
            # Leave input empty, click save
            await pilot.click("#save-btn")
            await pilot.pause()
            # Should not have dismissed (still showing modal)
            assert result == "sentinel"

    async def test_submit_via_enter(self):
        result = None

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, NoteModal, capture)
            for widget in app.screen.query(Input):
                if widget.id == "note-input":
                    widget.value = "Enter submitted"
                    widget.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert result == "Enter submitted"


class TestScheduleInterviewModal:
    async def test_schedule_returns_dict(self):
        result = None

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, ScheduleInterviewModal, capture)
            for widget in app.screen.query(Input):
                if widget.id == "date-input":
                    widget.value = "2025-03-15 14:00"
            await pilot.click("#schedule-btn")
            await pilot.pause()
            assert result is not None
            assert result["event_type"] == "phone_screen"
            assert result["scheduled_date"].year == 2025
            assert result["scheduled_date"].month == 3
            assert result["notes"] is None

    async def test_schedule_with_notes(self):
        result = None

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, ScheduleInterviewModal, capture)
            for widget in app.screen.query(Input):
                if widget.id == "date-input":
                    widget.value = "2025-03-15 14:00"
                elif widget.id == "notes-input":
                    widget.value = "Zoom link: https://zoom.us/123"
            await pilot.click("#schedule-btn")
            await pilot.pause()
            assert result is not None
            assert result["notes"] == "Zoom link: https://zoom.us/123"

    async def test_cancel_returns_none(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, ScheduleInterviewModal, capture)
            await pilot.click("#cancel-btn")
            await pilot.pause()
            assert result is None

    async def test_empty_date_shows_error(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, ScheduleInterviewModal, capture)
            # Leave date empty, click schedule
            await pilot.click("#schedule-btn")
            await pilot.pause()
            error = app.screen.query_one("#schedule-error", Static)
            assert "required" in error.content.lower()
            assert result == "sentinel"

    async def test_invalid_date_shows_error(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, ScheduleInterviewModal, capture)
            for widget in app.screen.query(Input):
                if widget.id == "date-input":
                    widget.value = "not-a-date"
            await pilot.click("#schedule-btn")
            await pilot.pause()
            error = app.screen.query_one("#schedule-error", Static)
            assert "invalid" in error.content.lower()
            assert result == "sentinel"

    async def test_escape_cancels(self):
        result = "sentinel"

        def capture(value):
            nonlocal result
            result = value

        app = ModalTestApp()
        async with app.run_test() as pilot:
            await _push_and_wait(app, pilot, ScheduleInterviewModal, capture)
            await pilot.press("escape")
            await pilot.pause()
            assert result is None
