"""Follow-up CLI command — check for stale applications and send follow-ups."""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.panel import Panel

from emplaiyed.core.database import get_default_db_path, init_db
from emplaiyed.core.models import ApplicationStatus
from emplaiyed.core.profile_store import get_default_profile_path, load_profile
from emplaiyed.followup import draft_followup, find_stale_applications, send_followup

logger = logging.getLogger(__name__)
console = Console()


def followup_command(
    stale_days: int = typer.Option(
        5, "--days", "-d", help="Days without response before triggering follow-up."
    ),
) -> None:
    """Check for applications needing follow-up and send messages."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        console.print("[red]No profile found. Run `emplaiyed profile build` first.[/red]")
        raise typer.Exit(code=1)

    profile = load_profile(profile_path)
    conn = init_db(get_default_db_path())

    try:
        stale = find_stale_applications(conn, stale_days=stale_days)

        if not stale:
            console.print("[green]No applications need follow-up right now.[/green]")
            return

        console.print(
            f"[bold]{len(stale)}[/bold] applications with no response "
            f"for {stale_days}+ days:\n"
        )

        sent_count = 0
        for i, (app_id, next_status, opp, days) in enumerate(stale, 1):
            followup_num = 1 if next_status == "FOLLOW_UP_1" else 2
            target = ApplicationStatus(next_status)

            console.print(
                f"[bold][{i}][/bold] {opp.company} — {opp.title}\n"
                f"    Sent: {days} days ago"
            )

            try:
                draft = asyncio.run(
                    draft_followup(profile, opp, followup_num, days)
                )
            except Exception as exc:
                console.print(f"    [red]Failed to draft: {exc}[/red]\n")
                continue

            console.print(Panel(
                f"[bold]Subject:[/bold] {draft.subject}\n\n{draft.body}",
                title=f"Follow-up #{followup_num}",
                border_style="yellow",
            ))

            send_followup(conn, app_id, draft, target)
            console.print(f"    [green]Follow-up sent[/green]\n")
            sent_count += 1

        if sent_count:
            console.print(f"\n[green]{sent_count} follow-ups sent.[/green]")
    finally:
        conn.close()
