"""Tests for the chat modal screen."""

from __future__ import annotations

from unittest.mock import patch

from pydantic_ai.models.test import TestModel
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from emplaiyed.console.chat_modal import ChatModal, _copy_to_clipboard


class ModalTestApp(App):
    """Minimal app shell for testing the chat modal."""

    def compose(self) -> ComposeResult:
        yield Static("Host app")


def _make_modal(response_text: str = "LLM response") -> ChatModal:
    model = TestModel(custom_output_text=response_text)
    return ChatModal(
        system_prompt="You are helpful.",
        company="TestCorp",
        _model_override=model,
    )


async def _push_and_wait(app, pilot, modal):
    app.push_screen(modal)
    await pilot.pause()
    await pilot.pause()


class TestChatModal:
    async def test_escape_closes(self):
        dismissed = False

        def on_dismiss(_):
            nonlocal dismissed
            dismissed = True

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal()
            app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert dismissed

    async def test_empty_input_not_submitted(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal()
            await _push_and_wait(app, pilot, modal)
            # Press enter on empty input — should be a no-op
            inp = app.screen.query_one("#chat-input", Input)
            inp.focus()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            # History should have no children (no query mounted)
            from textual.containers import VerticalScroll

            history = app.screen.query_one("#chat-history", VerticalScroll)
            assert len(history.children) == 0

    async def test_query_shows_in_history(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal()
            await _push_and_wait(app, pilot, modal)
            inp = app.screen.query_one("#chat-input", Input)
            inp.value = "What are my skills?"
            inp.focus()
            await pilot.press("enter")
            # Wait for worker to complete
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            from textual.containers import VerticalScroll

            history = app.screen.query_one("#chat-history", VerticalScroll)
            texts = [str(child.content) for child in history.children if isinstance(child, Static)]
            assert any("What are my skills?" in t for t in texts)

    async def test_response_shows_in_history(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal("Generated answer here")
            await _push_and_wait(app, pilot, modal)
            inp = app.screen.query_one("#chat-input", Input)
            inp.value = "Tell me something"
            inp.focus()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            from textual.containers import VerticalScroll

            history = app.screen.query_one("#chat-history", VerticalScroll)
            texts = [str(child.content) for child in history.children if isinstance(child, Static)]
            assert any("Generated answer here" in t for t in texts)

    async def test_response_copies_to_clipboard(self):
        copied_text = None

        def fake_copy(text):
            nonlocal copied_text
            copied_text = text
            return True

        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal("Copy this text")
            await _push_and_wait(app, pilot, modal)

            with patch("emplaiyed.console.chat_modal._copy_to_clipboard", side_effect=fake_copy):
                inp = app.screen.query_one("#chat-input", Input)
                inp.value = "test query"
                inp.focus()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

            assert copied_text == "Copy this text"

    async def test_clipboard_failure_shows_warning(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal("Some response")
            await _push_and_wait(app, pilot, modal)

            with patch("emplaiyed.console.chat_modal._copy_to_clipboard", return_value=False):
                inp = app.screen.query_one("#chat-input", Input)
                inp.value = "test query"
                inp.focus()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

            status = app.screen.query_one("#chat-status", Static)
            assert "could not copy" in str(status.content).lower()

    async def test_input_disabled_during_query(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            modal = _make_modal("response")
            await _push_and_wait(app, pilot, modal)
            inp = app.screen.query_one("#chat-input", Input)
            inp.value = "test"
            inp.focus()
            await pilot.press("enter")
            # After submitting, input should re-enable once worker finishes
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            assert not inp.disabled


class TestCopyToClipboard:
    def test_macos_uses_pbcopy(self):
        with patch("emplaiyed.console.chat_modal.sys") as mock_sys, \
             patch("emplaiyed.console.chat_modal.subprocess") as mock_sub:
            mock_sys.platform = "darwin"
            mock_sub.run.return_value = None
            result = _copy_to_clipboard("hello")
            mock_sub.run.assert_called_once_with(
                ["pbcopy"], input=b"hello", check=True
            )
            assert result is True

    def test_linux_uses_xclip(self):
        with patch("emplaiyed.console.chat_modal.sys") as mock_sys, \
             patch("emplaiyed.console.chat_modal.subprocess") as mock_sub:
            mock_sys.platform = "linux"
            mock_sub.run.return_value = None
            result = _copy_to_clipboard("hello")
            mock_sub.run.assert_called_once_with(
                ["xclip", "-selection", "clipboard"],
                input=b"hello",
                check=True,
            )
            assert result is True

    def test_linux_falls_back_to_xsel(self):
        with patch("emplaiyed.console.chat_modal.sys") as mock_sys, \
             patch("emplaiyed.console.chat_modal.subprocess") as mock_sub:
            mock_sys.platform = "linux"
            # First call (xclip) raises FileNotFoundError, second (xsel) succeeds
            mock_sub.run.side_effect = [FileNotFoundError, None]
            mock_sub.CalledProcessError = type("CalledProcessError", (Exception,), {})
            result = _copy_to_clipboard("hello")
            assert result is True
            assert mock_sub.run.call_count == 2

    def test_returns_false_on_failure(self):
        with patch("emplaiyed.console.chat_modal.sys") as mock_sys, \
             patch("emplaiyed.console.chat_modal.subprocess") as mock_sub:
            mock_sys.platform = "darwin"
            mock_sub.run.side_effect = FileNotFoundError
            mock_sub.CalledProcessError = type("CalledProcessError", (Exception,), {})
            result = _copy_to_clipboard("hello")
            assert result is False
