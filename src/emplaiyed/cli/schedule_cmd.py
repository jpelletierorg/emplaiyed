"""Schedule and calendar CLI commands."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from emplaiyed.core.database import (
    get_application,
    get_default_db_path,
    get_opportunity,
    init_db,
    list_applications,
    list_upcoming_events,
    save_event,
)
from emplaiyed.core.models import ApplicationStatus, ScheduledEvent
from emplaiyed.tracker.state_machine import can_transition, transition

console = Console()


def _get_connection():
    """Open (or create) the default SQLite database and return a connection."""
    return init_db(get_default_db_path())


def _resolve_application(conn, application_id: str):
    """Resolve an application ID with prefix matching. Returns the Application or exits."""
    app = get_application(conn, application_id)
    if app is None:
        # Try prefix match
        all_apps = list_applications(conn)
        matches = [a for a in all_apps if a.id.startswith(application_id)]
        if len(matches) == 1:
            app = matches[0]
        elif len(matches) > 1:
            console.print(
                f"[red]Ambiguous ID:[/red] '{application_id}' matches "
                f"{len(matches)} applications. Provide more characters."
            )
            raise typer.Exit(code=1)

    if app is None:
        console.print(
            f"[red]Application not found:[/red] '{application_id}'"
        )
        raise typer.Exit(code=1)

    return app


def _format_event_type(event_type: str) -> str:
    """Format an event type string for display (e.g. 'phone_screen' -> 'Phone Screen')."""
    return event_type.replace("_", " ").title()


def schedule_command(
    application_id: str = typer.Argument(
        help="The application ID (or prefix)."
    ),
    event_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Event type (e.g. phone_screen, technical_interview, onsite, follow_up_due).",
    ),
    date_str: str = typer.Option(
        ...,
        "--date",
        "-d",
        help="Scheduled date/time (e.g. '2025-01-14 14:00').",
    ),
    notes: Optional[str] = typer.Option(
        None,
        "--notes",
        "-n",
        help="Optional notes about the event.",
    ),
) -> None:
    """Schedule an event (interview, follow-up, etc.) for an application."""
    # Parse the date
    try:
        scheduled_date = datetime.fromisoformat(date_str)
    except ValueError:
        console.print(
            f"[red]Invalid date format:[/red] '{date_str}'\n"
            "Use ISO format, e.g. '2025-01-14 14:00' or '2025-01-14T14:00:00'."
        )
        raise typer.Exit(code=1)

    conn = _get_connection()
    try:
        app = _resolve_application(conn, application_id)

        # Create and save the event
        event = ScheduledEvent(
            application_id=app.id,
            event_type=event_type,
            scheduled_date=scheduled_date,
            notes=notes,
            created_at=datetime.now(),
        )
        save_event(conn, event)

        # Auto-transition to INTERVIEW_SCHEDULED if appropriate
        if can_transition(app.status, ApplicationStatus.INTERVIEW_SCHEDULED):
            transition(conn, app.id, ApplicationStatus.INTERVIEW_SCHEDULED)

        # Look up opportunity for display
        opp = get_opportunity(conn, app.opportunity_id)
        company = opp.company if opp else "Unknown"
        role = opp.title if opp else "Unknown"

        formatted_type = _format_event_type(event_type)
        formatted_date = scheduled_date.strftime("%b %d at %I:%M %p")

        console.print(
            f"\n[green]\\u2713[/green] {formatted_type} scheduled for {formatted_date}"
        )
        console.print(f"  Application: {company} — {role}")
        if notes:
            console.print(f"  Notes: {notes}")
        console.print(
            f"  Run `emplaiyed prep {app.id[:8]}` anytime.\n"
        )
    finally:
        conn.close()


def calendar_command() -> None:
    """Show all upcoming scheduled events."""
    conn = _get_connection()
    try:
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
            # Look up application and opportunity
            app = get_application(conn, event.application_id)
            if app:
                opp = get_opportunity(conn, app.opportunity_id)
                company = opp.company if opp else "Unknown"
            else:
                company = "Unknown"

            date_str = event.scheduled_date.strftime("%b %d")
            time_str = event.scheduled_date.strftime("%H:%M")
            # If time is midnight, show a dash instead
            if event.scheduled_date.hour == 0 and event.scheduled_date.minute == 0:
                time_str = "\u2014"

            table.add_row(
                date_str,
                time_str,
                company,
                _format_event_type(event.event_type),
                event.application_id[:8],
            )

        console.print()
        console.print(table)
        console.print()
    finally:
        conn.close()
