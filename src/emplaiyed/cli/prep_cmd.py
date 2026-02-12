"""Interview prep CLI command."""

from __future__ import annotations

import asyncio

import typer
from rich.panel import Panel

from emplaiyed.cli import cli_error, console, db_connection, require_profile, resolve_application
from emplaiyed.core.database import get_opportunity
from emplaiyed.prep import generate_prep


def prep_command(
    application_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Generate an interview prep cheat sheet for an application."""
    profile = require_profile()

    with db_connection() as conn:
        app = resolve_application(conn, application_id)
        opp = get_opportunity(conn, app.opportunity_id)
        if opp is None:
            cli_error("Opportunity not found for this application.")

        console.print(f"\nPreparing for: [bold]{opp.company}[/bold] — {opp.title}\n")

        try:
            sheet = asyncio.run(generate_prep(profile, opp))
        except Exception as exc:
            cli_error(f"Prep generation failed: {exc}")

        lines = [f"[bold]Company:[/bold] {sheet.company_summary}\n"]

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
