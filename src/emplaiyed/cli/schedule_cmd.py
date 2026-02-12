"""Schedule and calendar CLI commands."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from rich.table import Table

from emplaiyed.cli import cli_error, console, db_connection, resolve_application
from emplaiyed.core.database import get_application, get_opportunity, list_upcoming_events, save_event
from emplaiyed.core.models import ApplicationStatus, ScheduledEvent
from emplaiyed.tracker.state_machine import can_transition, transition


def _format_event_type(event_type: str) -> str:
    return event_type.replace("_", " ").title()


def schedule_command(
    application_id: str = typer.Argument(help="The application ID (or prefix)."),
    event_type: str = typer.Option(
        ..., "--type", "-t",
        help="Event type (e.g. phone_screen, technical_interview, onsite, follow_up_due).",
    ),
    date_str: str = typer.Option(
        ..., "--date", "-d", help="Scheduled date/time (e.g. '2025-01-14 14:00').",
    ),
    notes: Optional[str] = typer.Option(
        None, "--notes", "-n", help="Optional notes about the event.",
    ),
) -> None:
    """Schedule an event (interview, follow-up, etc.) for an application."""
    try:
        scheduled_date = datetime.fromisoformat(date_str)
    except ValueError:
        cli_error(
            f"Invalid date format: '{date_str}'\n"
            "Use ISO format, e.g. '2025-01-14 14:00' or '2025-01-14T14:00:00'."
        )

    with db_connection() as conn:
        app = resolve_application(conn, application_id)

        event = ScheduledEvent(
            application_id=app.id,
            event_type=event_type,
            scheduled_date=scheduled_date,
            notes=notes,
            created_at=datetime.now(),
        )
        save_event(conn, event)

        if can_transition(app.status, ApplicationStatus.INTERVIEW_SCHEDULED):
            transition(conn, app.id, ApplicationStatus.INTERVIEW_SCHEDULED)

        opp = get_opportunity(conn, app.opportunity_id)
        company = opp.company if opp else "Unknown"
        role = opp.title if opp else "Unknown"

        formatted_date = scheduled_date.strftime("%b %d at %I:%M %p")
        console.print(f"\n[green]\\u2713[/green] {_format_event_type(event_type)} scheduled for {formatted_date}")
        console.print(f"  Application: {company} — {role}")
        if notes:
            console.print(f"  Notes: {notes}")
        console.print(f"  Run `emplaiyed prep {app.id[:8]}` anytime.\n")


def calendar_command() -> None:
    """Show all upcoming scheduled events."""
    with db_connection() as conn:
        events = list_upcoming_events(conn)

        if not events:
            console.print("\n[dim]No upcoming events scheduled.[/dim]\n")
            return

        table = Table(title="Upcoming Events")
        table.add_column("Date", style="cyan")
        table.add_column("Time", style="cyan")
        table.add_column("Company")
        table.add_column("Type")
        table.add_column("Application", style="dim")

        for event in events:
            app = get_application(conn, event.application_id)
            opp = get_opportunity(conn, app.opportunity_id) if app else None
            company = opp.company if opp else "Unknown"

            date_str = event.scheduled_date.strftime("%b %d")
            time_str = event.scheduled_date.strftime("%H:%M")
            if event.scheduled_date.hour == 0 and event.scheduled_date.minute == 0:
                time_str = "\u2014"

            table.add_row(date_str, time_str, company, _format_event_type(event.event_type), event.application_id[:8])

        console.print()
        console.print(table)
        console.print()
