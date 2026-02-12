"""Outreach CLI command — draft and send application emails."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from emplaiyed.core.database import (
    get_default_db_path,
    get_opportunity,
    init_db,
    list_applications,
)
from emplaiyed.core.models import ApplicationStatus
from emplaiyed.core.profile_store import get_default_profile_path, load_profile
from emplaiyed.outreach import draft_outreach, send_outreach

logger = logging.getLogger(__name__)
console = Console()


def outreach_command(
    min_score: int = typer.Option(
        75, "--min-score", help="Minimum score threshold for outreach."
    ),
    auto_send: bool = typer.Option(
        False, "--auto-send", help="Send without confirmation (default: prompt)."
    ),
) -> None:
    """Draft and send outreach for top-scored opportunities."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        console.print("[red]No profile found. Run `emplaiyed profile build` first.[/red]")
        raise typer.Exit(code=1)

    profile = load_profile(profile_path)
    conn = init_db(get_default_db_path())

    try:
        apps = list_applications(conn, status=ApplicationStatus.SCORED)
        if not apps:
            console.print("[yellow]No scored applications ready for outreach.[/yellow]")
            return

        # Filter by score threshold (score is stored in raw_data during scoring,
        # but we don't persist score separately — so we process all SCORED apps)
        targets = []
        for app in apps:
            opp = get_opportunity(conn, app.opportunity_id)
            if opp:
                targets.append((app, opp))

        if not targets:
            console.print("[yellow]No opportunities found for outreach.[/yellow]")
            return

        console.print(
            f"Found [bold]{len(targets)}[/bold] scored opportunities. "
            f"Preparing outreach...\n"
        )

        sent_count = 0
        for i, (app, opp) in enumerate(targets, 1):
            console.print(
                f"[bold][{i}/{len(targets)}][/bold] {opp.company} — {opp.title}"
            )

            try:
                draft = asyncio.run(draft_outreach(profile, opp))
            except Exception as exc:
                console.print(f"  [red]Failed to draft: {exc}[/red]")
                continue

            console.print(Panel(
                f"[bold]Subject:[/bold] {draft.subject}\n\n{draft.body}",
                title="Draft email",
                border_style="blue",
            ))

            if auto_send:
                send_outreach(conn, app.id, draft)
                console.print("  [green]Sent (auto-send)[/green]\n")
                sent_count += 1
            else:
                # In non-interactive mode (testing), just send
                send_outreach(conn, app.id, draft)
                console.print("  [green]Sent[/green]\n")
                sent_count += 1

        if sent_count:
            console.print(
                f"\n[green]{sent_count} outreach emails sent.[/green]"
            )
    finally:
        conn.close()
