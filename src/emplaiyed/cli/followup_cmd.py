"""Follow-up CLI command — check for stale applications and send follow-ups."""

from __future__ import annotations

import asyncio

import typer
from rich.panel import Panel

from emplaiyed.cli import console, db_connection, require_profile
from emplaiyed.core.database import get_application
from emplaiyed.core.models import ApplicationStatus
from emplaiyed.followup import draft_followup, enqueue_followup, find_stale_applications


def followup_command(
    stale_days: int = typer.Option(
        5, "--days", "-d", help="Days without response before triggering follow-up."
    ),
) -> None:
    """Check for applications needing follow-up and send messages."""
    profile = require_profile()

    with db_connection() as conn:
        stale = find_stale_applications(conn, stale_days=stale_days)

        if not stale:
            console.print("[green]No applications need follow-up right now.[/green]")
            return

        console.print(
            f"[bold]{len(stale)}[/bold] applications with no response "
            f"for {stale_days}+ days:\n"
        )

        queued_count = 0
        for i, (app_id, next_status, opp, days) in enumerate(stale, 1):
            followup_num = 1 if next_status == "FOLLOW_UP_1" else 2
            target = ApplicationStatus(next_status)

            console.print(
                f"[bold][{i}][/bold] {opp.company} — {opp.title}\n"
                f"    Sent: {days} days ago"
            )

            try:
                draft = asyncio.run(draft_followup(profile, opp, followup_num, days))
            except Exception as exc:
                console.print(f"    [red]Failed to draft: {exc}[/red]\n")
                continue

            console.print(Panel(
                f"[bold]Subject:[/bold] {draft.subject}\n\n{draft.body}",
                title=f"Follow-up #{followup_num}",
                border_style="yellow",
            ))

            app = get_application(conn, app_id)
            previous = app.status if app else ApplicationStatus.OUTREACH_SENT

            item = enqueue_followup(conn, app_id, opp, draft, target, previous, followup_num)
            console.print(
                f"    [blue]Work item created:[/blue] {item.id[:8]}\n"
                f"    Run `emplaiyed work next` to review.\n"
            )
            queued_count += 1

        if queued_count:
            console.print(
                f"\n[blue]{queued_count} work items created.[/blue] "
                f"Run `emplaiyed work list` to see your queue."
            )
