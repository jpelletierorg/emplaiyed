"""Search modal — full-text search across opportunities."""

from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from emplaiyed.core.database import search_opportunities
from emplaiyed.core.models import Application, Opportunity


class SearchModal(ModalScreen[str | None]):
    """Modal for searching opportunities by keyword.

    Returns the *application ID* of the selected result, or ``None`` if
    the user cancels.  Results with no application are shown but not
    selectable (they have no pipeline entry to navigate to).
    """

    CSS = """
    SearchModal {
        align: center middle;
    }
    #search-dialog {
        width: 90;
        height: 80%;
        border: thick $accent;
        padding: 1 2;
    }
    #search-input {
        width: 100%;
        margin: 1 0 0 0;
    }
    #search-results {
        height: 1fr;
        margin: 1 0 0 0;
    }
    #search-status {
        height: 1;
        margin: 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self._conn = conn
        self._result_apps: list[str | None] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label("Search Opportunities")
            yield Input(
                placeholder="Type keywords and press Enter (e.g. devops ChatCorp)…",
                id="search-input",
            )
            yield OptionList(id="search-results")
            yield Static("Press Enter to search, Escape to close", id="search-status")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        self._run_search(query)

    def _run_search(self, query: str) -> None:
        results = search_opportunities(self._conn, query, limit=20)
        option_list = self.query_one("#search-results", OptionList)
        option_list.clear_options()
        self._result_apps.clear()

        if not results:
            self.query_one("#search-status", Static).update("No results found.")
            return

        for opp, app in results:
            label = _format_result(opp, app)
            option_list.add_option(Option(label))
            self._result_apps.append(app.id if app else None)

        self.query_one("#search-status", Static).update(
            f"{len(results)} result(s) — highlight one and press Enter to navigate"
        )
        option_list.highlighted = 0
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._result_apps):
            app_id = self._result_apps[idx]
            if app_id is not None:
                self.dismiss(app_id)
            else:
                self.query_one("#search-status", Static).update(
                    "This opportunity has no application — cannot navigate."
                )

    def action_cancel(self) -> None:
        self.dismiss(None)


def _format_result(opp: Opportunity, app: Application | None) -> str:
    """Build a one-line label for a search result."""
    parts: list[str] = []

    if app is not None and app.score is not None:
        parts.append(f"[{app.score:3d}]")
    else:
        parts.append("[   ]")

    parts.append(f"{opp.company} — {opp.title}")

    if opp.location:
        parts.append(f"({opp.location})")

    if app is not None:
        parts.append(f"[{app.status.value}]")
    else:
        parts.append("[no app]")

    return " ".join(parts)
