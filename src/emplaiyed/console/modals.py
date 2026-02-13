"""Modal screens for pipeline actions (notes, scheduling, etc.)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static


class NoteModal(ModalScreen[str | None]):
    """Modal for adding a free-text note to an application."""

    CSS = """
    NoteModal {
        align: center middle;
    }
    #note-dialog {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $accent;
        padding: 1 2;
    }
    #note-input {
        width: 100%;
        margin: 1 0;
    }
    .modal-buttons {
        height: 3;
        align: center middle;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="note-dialog"):
            yield Label("Add Note")
            yield Input(placeholder="Enter note text...", id="note-input")
            from textual.containers import Horizontal

            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            text = self.query_one("#note-input", Input).value.strip()
            if text:
                self.dismiss(text)
            else:
                self.query_one("#note-input", Input).focus()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)


_EVENT_TYPES = [
    ("Phone Screen", "phone_screen"),
    ("Technical Interview", "technical_interview"),
    ("Onsite", "onsite"),
    ("Behavioral", "behavioral"),
    ("Other", "other"),
]


class LogFollowUpModal(ModalScreen[str | None]):
    """Modal for logging a follow-up sent."""

    CSS = """
    LogFollowUpModal {
        align: center middle;
    }
    #followup-dialog {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $accent;
        padding: 1 2;
    }
    #followup-input {
        width: 100%;
        margin: 1 0;
    }
    .modal-buttons {
        height: 3;
        align: center middle;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="followup-dialog"):
            yield Label("Log Follow-Up")
            yield Input(placeholder="What did you send?", id="followup-input")
            from textual.containers import Horizontal

            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            text = self.query_one("#followup-input", Input).value.strip()
            if text:
                self.dismiss(text)
            else:
                self.query_one("#followup-input", Input).focus()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ResponseReceivedModal(ModalScreen[dict | None]):
    """Modal for capturing a response received, with optional scheduling.

    Returns a dict with keys: description, schedule (dict or None).
    Or None if cancelled.
    """

    CSS = """
    ResponseReceivedModal {
        align: center middle;
    }
    #response-dialog {
        width: 70;
        height: auto;
        max-height: 35;
        border: thick $accent;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
    }
    #response-input, #response-date-input, #response-notes-input {
        width: 100%;
    }
    #response-event-type-select {
        width: 100%;
    }
    .modal-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    #response-error {
        color: $error;
        margin: 1 0 0 0;
    }
    .section-header {
        margin-top: 1;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    EVENT_TYPES = _EVENT_TYPES

    def compose(self) -> ComposeResult:
        with Vertical(id="response-dialog"):
            yield Label("Response Received")

            yield Label("What was the response?", classes="field-label")
            yield Input(placeholder="Describe the response...", id="response-input")

            yield Label("Schedule an interview (optional)", classes="section-header")

            yield Label("Event Type", classes="field-label")
            yield Select(
                [(label, value) for label, value in self.EVENT_TYPES],
                id="response-event-type-select",
                value="phone_screen",
            )

            yield Label("Date & Time (YYYY-MM-DD HH:MM)", classes="field-label")
            yield Input(placeholder="2025-03-15 14:00", id="response-date-input")

            yield Label("Notes (optional)", classes="field-label")
            yield Input(placeholder="Meeting link, location, etc.", id="response-notes-input")

            yield Static("", id="response-error")

            from textual.containers import Horizontal

            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._try_submit()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _try_submit(self) -> None:
        from datetime import datetime

        description = self.query_one("#response-input", Input).value.strip()
        if not description:
            self.query_one("#response-error", Static).update("Description is required.")
            return

        date_str = self.query_one("#response-date-input", Input).value.strip()
        schedule = None

        if date_str:
            try:
                scheduled_date = datetime.fromisoformat(date_str)
            except ValueError:
                self.query_one("#response-error", Static).update(
                    "Invalid date format. Use YYYY-MM-DD HH:MM"
                )
                return

            event_type = self.query_one("#response-event-type-select", Select).value
            notes = self.query_one("#response-notes-input", Input).value.strip() or None
            schedule = {
                "event_type": event_type,
                "scheduled_date": scheduled_date,
                "notes": notes,
            }

        self.dismiss({
            "description": description,
            "schedule": schedule,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class ScheduleInterviewModal(ModalScreen[dict | None]):
    """Modal for scheduling an interview event.

    Returns a dict with keys: event_type, scheduled_date, notes.
    Or None if cancelled.
    """

    CSS = """
    ScheduleInterviewModal {
        align: center middle;
    }
    #schedule-dialog {
        width: 70;
        height: auto;
        max-height: 30;
        border: thick $accent;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
    }
    #event-type-select {
        width: 100%;
    }
    #date-input, #notes-input {
        width: 100%;
    }
    .modal-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    #schedule-error {
        color: $error;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    EVENT_TYPES = _EVENT_TYPES

    def compose(self) -> ComposeResult:
        with Vertical(id="schedule-dialog"):
            yield Label("Schedule Interview")

            yield Label("Event Type", classes="field-label")
            yield Select(
                [(label, value) for label, value in self.EVENT_TYPES],
                id="event-type-select",
                value="phone_screen",
            )

            yield Label("Date & Time (YYYY-MM-DD HH:MM)", classes="field-label")
            yield Input(placeholder="2025-03-15 14:00", id="date-input")

            yield Label("Notes (optional)", classes="field-label")
            yield Input(placeholder="Meeting link, location, etc.", id="notes-input")

            yield Static("", id="schedule-error")

            from textual.containers import Horizontal

            with Horizontal(classes="modal-buttons"):
                yield Button("Schedule", variant="primary", id="schedule-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "schedule-btn":
            self._try_submit()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _try_submit(self) -> None:
        from datetime import datetime

        date_str = self.query_one("#date-input", Input).value.strip()
        if not date_str:
            self.query_one("#schedule-error", Static).update("Date is required.")
            return

        try:
            scheduled_date = datetime.fromisoformat(date_str)
        except ValueError:
            self.query_one("#schedule-error", Static).update(
                "Invalid date format. Use YYYY-MM-DD HH:MM"
            )
            return

        event_type = self.query_one("#event-type-select", Select).value
        notes = self.query_one("#notes-input", Input).value.strip() or None

        self.dismiss({
            "event_type": event_type,
            "scheduled_date": scheduled_date,
            "notes": notes,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)
