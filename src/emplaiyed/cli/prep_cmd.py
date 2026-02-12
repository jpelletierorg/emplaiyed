"""Interview prep CLI command."""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.panel import Panel

from emplaiyed.core.database import (
    get_application,
    get_default_db_path,
    get_opportunity,
    init_db,
    list_applications,
)
from emplaiyed.core.profile_store import get_default_profile_path, load_profile
from emplaiyed.prep import generate_prep

logger = logging.getLogger(__name__)
console = Console()


def prep_command(
    application_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Generate an interview prep cheat sheet for an application."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        console.print("[red]No profile found. Run `emplaiyed profile build` first.[/red]")
        raise typer.Exit(code=1)

    profile = load_profile(profile_path)
    conn = init_db(get_default_db_path())

    try:
        # Resolve application ID (prefix match)
        app = get_application(conn, application_id)
        if app is None:
            all_apps = list_applications(conn)
            matches = [a for a in all_apps if a.id.startswith(application_id)]
            if len(matches) == 1:
                app = matches[0]
            elif len(matches) > 1:
                console.print(
                    f"[red]Ambiguous ID:[/red] '{application_id}' matches "
                    f"{len(matches)} applications."
                )
                raise typer.Exit(code=1)

        if app is None:
            console.print(f"[red]Application not found:[/red] '{application_id}'")
            raise typer.Exit(code=1)

        opp = get_opportunity(conn, app.opportunity_id)
        if opp is None:
            console.print("[red]Opportunity not found for this application.[/red]")
            raise typer.Exit(code=1)

        console.print(
            f"\nPreparing for: [bold]{opp.company}[/bold] — {opp.title}\n"
        )

        try:
            sheet = asyncio.run(generate_prep(profile, opp))
        except Exception as exc:
            console.print(f"[red]Prep generation failed: {exc}[/red]")
            raise typer.Exit(code=1)

        # Display the cheat sheet
        lines = []
        lines.append(f"[bold]Company:[/bold] {sheet.company_summary}\n")

        lines.append("[bold]LIKELY QUESTIONS[/bold]")
        for j, q in enumerate(sheet.likely_questions, 1):
            lines.append(f"  {j}. {q}")
            if j <= len(sheet.suggested_answers):
                lines.append(f"     -> {sheet.suggested_answers[j - 1]}")
        lines.append("")

        lines.append("[bold]QUESTIONS TO ASK THEM[/bold]")
        for q in sheet.questions_to_ask:
            lines.append(f"  * {q}")
        lines.append("")

        lines.append(f"[bold]SALARY NOTES[/bold]\n  {sheet.salary_notes}\n")

        if sheet.red_flags:
            lines.append("[bold]RED FLAGS TO WATCH FOR[/bold]")
            for rf in sheet.red_flags:
                lines.append(f"  ! {rf}")

        console.print(Panel(
            "\n".join(lines),
            title=f"Cheat Sheet: {opp.company} — {opp.title}",
            border_style="green",
        ))
    finally:
        conn.close()
