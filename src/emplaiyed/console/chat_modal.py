"""Chat modal — interactive LLM assistant with clipboard copy."""

from __future__ import annotations

import subprocess
import sys

from pydantic_ai.models import Model
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. Returns False on failure."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        else:
            # Linux: try xclip first, fall back to xsel
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(),
                    check=True,
                )
            except FileNotFoundError:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode(),
                    check=True,
                )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


class ChatModal(ModalScreen[None]):
    """Interactive chat modal with LLM context from application assets."""

    CSS = """
    ChatModal {
        align: center middle;
    }
    #chat-dialog {
        width: 90;
        height: 80%;
        border: thick $accent;
        padding: 1 2;
    }
    #chat-history {
        height: 1fr;
        border: solid $surface;
        padding: 0 1;
    }
    .chat-query {
        color: $text;
        text-style: bold;
        margin: 1 0 0 0;
    }
    .chat-response {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    #chat-input {
        width: 100%;
        margin: 1 0 0 0;
    }
    #chat-status {
        height: 1;
        margin: 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(
        self,
        system_prompt: str,
        company: str,
        _model_override: Model | None = None,
    ) -> None:
        super().__init__()
        self._system_prompt = system_prompt
        self._company = company
        self._model_override = _model_override

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-dialog"):
            yield Label(f"Chat — {self._company}")
            yield VerticalScroll(id="chat-history")
            yield Input(placeholder="Type a question…", id="chat-input")
            yield Static("", id="chat-status")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        event.input.value = ""
        event.input.disabled = True

        history = self.query_one("#chat-history", VerticalScroll)
        history.mount(Static(f"> {query}", classes="chat-query"))

        self.query_one("#chat-status", Static).update("Thinking…")
        self._run_query(query)

    @work(exclusive=True)
    async def _run_query(self, query: str) -> None:
        from emplaiyed.generation.chat_assistant import chat

        try:
            response = await chat(
                query,
                system_prompt=self._system_prompt,
                _model_override=self._model_override,
            )
        except Exception as exc:
            self.query_one("#chat-status", Static).update(f"Error: {exc}")
            self.query_one("#chat-input", Input).disabled = False
            return

        history = self.query_one("#chat-history", VerticalScroll)
        history.mount(Static(response, classes="chat-response"))
        history.scroll_end()

        copied = _copy_to_clipboard(response)
        if copied:
            self.query_one("#chat-status", Static).update("Copied to clipboard")
        else:
            self.query_one("#chat-status", Static).update(
                "Could not copy to clipboard — response is visible above"
            )

        self.query_one("#chat-input", Input).disabled = False

    def action_cancel(self) -> None:
        self.dismiss(None)
