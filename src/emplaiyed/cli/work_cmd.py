"""Work queue CLI commands — list, show, next, done, skip, pass."""

from __future__ import annotations

from datetime import datetime

import typer
from rich.panel import Panel
from rich.table import Table

from emplaiyed.cli import (
    cli_error,
    console,
    db_connection,
    resolve_application,
    resolve_work_item,
)
from emplaiyed.core.database import (
    get_application,
    get_opportunity,
    list_pending_work_items,
)
from emplaiyed.core.models import ApplicationStatus, WorkStatus
from emplaiyed.tracker.state_machine import can_transition, transition
from emplaiyed.work.queue import complete_work_item, skip_work_item

work_app = typer.Typer(
    name="work",
    help="Human-in-the-loop work queue.",
    no_args_is_help=True,
)


def _format_age(item) -> str:
    """Format time since creation as a human-readable string."""
    delta = datetime.now() - item.created_at
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours" if hours > 1 else "1 hour"
    days = hours // 24
    return f"{days} days" if days > 1 else "1 day"


@work_app.command("list")
def list_command() -> None:
    """Show all pending work items."""
    with db_connection() as conn:
        items = list_pending_work_items(conn)
        if not items:
            console.print("[green]No pending work items. You're all caught up![/green]")
            return

        table = Table(title=f"Work Queue ({len(items)} pending)")
        table.add_column("ID", style="dim")
        table.add_column("Type")
        table.add_column("Task")
        table.add_column("Age", justify="right")

        for item in items:
            table.add_row(
                item.id[:8] + "..",
                item.work_type.value.lower(),
                item.title,
                _format_age(item),
            )

        console.print(table)


@work_app.command("next")
def next_command() -> None:
    """Show the oldest pending work item with full instructions."""
    with db_connection() as conn:
        items = list_pending_work_items(conn)
        if not items:
            console.print("[green]No pending work items. You're all caught up![/green]")
            return
        _display_work_item(conn, items[0])


@work_app.command("show")
def show_command(
    item_id: str = typer.Argument(help="Work item ID (or prefix)."),
) -> None:
    """Show a specific work item with full instructions."""
    with db_connection() as conn:
        item = resolve_work_item(conn, item_id)
        _display_work_item(conn, item)


@work_app.command("done")
def done_command(
    item_id: str = typer.Argument(help="Work item ID (or prefix)."),
) -> None:
    """Mark a work item as done and advance the application state."""
    with db_connection() as conn:
        item = resolve_work_item(conn, item_id)
        if item.status != WorkStatus.PENDING:
            console.print(f"[yellow]Work item is already {item.status.value}.[/yellow]")
            return

        completed = complete_work_item(conn, item.id)

        app = get_application(conn, completed.application_id)
        opp = get_opportunity(conn, app.opportunity_id) if app else None
        company = opp.company if opp else "Unknown"

        console.print(
            f"[green]Done![/green] {company} application advanced to "
            f"{completed.target_status}."
        )
        remaining = len(list_pending_work_items(conn))
        console.print(f"{remaining} items remaining in your queue.")


@work_app.command("skip")
def skip_command(
    item_id: str = typer.Argument(help="Work item ID (or prefix)."),
) -> None:
    """Skip a work item and revert the application state."""
    with db_connection() as conn:
        item = resolve_work_item(conn, item_id)
        if item.status != WorkStatus.PENDING:
            console.print(f"[yellow]Work item is already {item.status.value}.[/yellow]")
            return

        skipped = skip_work_item(conn, item.id)

        app = get_application(conn, skipped.application_id)
        opp = get_opportunity(conn, app.opportunity_id) if app else None
        company = opp.company if opp else "Unknown"

        console.print(
            f"[yellow]Skipped.[/yellow] {company} application reverted to "
            f"{skipped.previous_status}."
        )
        remaining = len(list_pending_work_items(conn))
        console.print(f"{remaining} items remaining in your queue.")


@work_app.command("pass")
def pass_command(
    app_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Mark an application as PASSED (not interested)."""
    with db_connection() as conn:
        app_obj = resolve_application(conn, app_id)

        if not can_transition(app_obj.status, ApplicationStatus.PASSED):
            cli_error(f"Cannot pass application in {app_obj.status.value} state.")

        transition(conn, app_obj.id, ApplicationStatus.PASSED)

        opp = get_opportunity(conn, app_obj.opportunity_id)
        company = opp.company if opp else "Unknown"
        role = opp.title if opp else "Unknown"

        console.print(
            f"[yellow]Passed.[/yellow] {company} — {role} marked as not interested."
        )


def _display_work_item(conn, item) -> None:
    """Render a work item as a rich panel."""
    app = get_application(conn, item.application_id)
    opp = get_opportunity(conn, app.opportunity_id) if app else None

    lines = []
    if opp:
        lines.append(f"[bold]Company:[/bold]  {opp.company}")
        lines.append(f"[bold]Role:[/bold]     {opp.title}")
        if opp.location:
            lines.append(f"[bold]Location:[/bold] {opp.location}")
        if opp.source_url:
            lines.append(f"[bold]URL:[/bold]      {opp.source_url}")
        lines.append("")

    lines.append(item.instructions)
    lines.append("")
    lines.append(f"[dim]emplaiyed work done {item.id[:8]}[/dim]")
    lines.append(f"[dim]emplaiyed work skip {item.id[:8]}[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title=item.title,
        border_style="blue",
    ))
