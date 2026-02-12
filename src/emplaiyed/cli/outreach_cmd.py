"""Outreach CLI command — generate assets or draft emails for applications."""

from __future__ import annotations

import asyncio

import typer
from rich.panel import Panel

from emplaiyed.cli import console, db_connection, require_profile
from emplaiyed.core.database import get_opportunity, list_applications, list_work_items
from emplaiyed.core.models import ApplicationStatus
from emplaiyed.generation.pipeline import generate_assets_and_enqueue
from emplaiyed.outreach import draft_outreach, send_outreach


def outreach_command(
    min_score: int = typer.Option(
        75, "--min-score", help="Minimum score threshold for outreach."
    ),
    auto_send: bool = typer.Option(
        False, "--auto-send", help="Send without confirmation (default: prompt)."
    ),
) -> None:
    """Draft and send outreach for top-scored opportunities."""
    profile = require_profile()

    with db_connection() as conn:
        apps = list_applications(conn, status=ApplicationStatus.SCORED)
        if not apps:
            console.print("[yellow]No scored applications ready for outreach.[/yellow]")
            return

        # Filter to apps that don't already have work items
        apps_with_work = {w.application_id for w in list_work_items(conn)}
        targets = [
            (a, opp)
            for a in apps
            if a.id not in apps_with_work
            for opp in [get_opportunity(conn, a.opportunity_id)]
            if opp
        ]

        if not targets:
            console.print("[yellow]No opportunities need outreach (all have work items).[/yellow]")
            return

        console.print(f"Found [bold]{len(targets)}[/bold] scored opportunities. Preparing...\n")

        queued_count = 0
        for i, (app_record, opp) in enumerate(targets, 1):
            console.print(f"[bold][{i}/{len(targets)}][/bold] {opp.company} — {opp.title}")

            if auto_send:
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
                send_outreach(conn, app_record.id, draft)
                console.print("  [green]Sent (auto-send)[/green]\n")
            else:
                try:
                    paths = asyncio.run(
                        generate_assets_and_enqueue(conn, profile, opp, app_record.id)
                    )
                    console.print(
                        f"  [blue]Assets generated + work item created[/blue]\n"
                        f"  CV: {paths.cv_pdf}\n"
                        f"  Letter: {paths.letter_pdf}\n"
                    )
                except Exception as exc:
                    console.print(f"  [red]Failed: {exc}[/red]")
                    continue

            queued_count += 1

        if queued_count:
            action = "outreach emails sent" if auto_send else "work items created with assets"
            color = "green" if auto_send else "blue"
            console.print(f"\n[{color}]{queued_count} {action}.[/{color}]")
            if not auto_send:
                console.print("Run `emplaiyed work list` to see your queue.")
