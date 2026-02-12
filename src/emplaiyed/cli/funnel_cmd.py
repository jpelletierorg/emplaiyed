"""Funnel / application tracking CLI commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from emplaiyed.core.database import (
    get_default_db_path,
    init_db,
    get_application,
    get_opportunity,
    list_applications,
    list_interactions,
)
from emplaiyed.core.models import ApplicationStatus

funnel_app = typer.Typer(
    name="funnel",
    help="View and manage your application funnel.",
    no_args_is_help=True,
)

console = Console()


def _get_connection():
    """Open (or create) the default SQLite database and return a connection."""
    return init_db(get_default_db_path())


@funnel_app.command("status")
def funnel_status() -> None:
    """Show a summary of how many applications are in each pipeline stage."""
    conn = _get_connection()
    try:
        applications = list_applications(conn)

        if not applications:
            console.print(
                Panel(
                    "No applications tracked yet.\n\n"
                    "Add opportunities and start applying to see your funnel here.",
                    title="Funnel Status",
                    border_style="yellow",
                )
            )
            return

        # Count applications per status
        counts: dict[str, int] = {}
        for status in ApplicationStatus:
            counts[status.value] = 0
        for app in applications:
            counts[app.status.value] += 1

        table = Table(title="Funnel Status")
        table.add_column("Stage", style="cyan")
        table.add_column("Count", justify="right")

        for status in ApplicationStatus:
            count = counts[status.value]
            style = "bold green" if count > 0 else "dim"
            table.add_row(status.value, str(count), style=style)

        table.add_section()
        table.add_row("[bold]TOTAL[/bold]", f"[bold]{len(applications)}[/bold]")

        console.print(table)
    finally:
        conn.close()


@funnel_app.command("list")
def funnel_list(
    stage: Optional[str] = typer.Option(
        None,
        "--stage",
        "-s",
        help="Filter by application stage (e.g. SCORED, OUTREACH_SENT).",
    ),
) -> None:
    """List all applications, optionally filtered by stage."""
    conn = _get_connection()
    try:
        filters = {}
        if stage:
            try:
                status_enum = ApplicationStatus(stage.upper())
            except ValueError:
                valid = ", ".join(s.value for s in ApplicationStatus)
                console.print(
                    f"[red]Invalid stage:[/red] {stage}\n"
                    f"Valid stages: {valid}"
                )
                raise typer.Exit(code=1)
            filters["status"] = status_enum

        applications = list_applications(conn, **filters)

        if not applications:
            if stage:
                console.print(
                    f"No applications with stage [bold]{stage.upper()}[/bold]."
                )
            else:
                console.print(
                    Panel(
                        "No applications tracked yet.",
                        title="Applications",
                        border_style="yellow",
                    )
                )
            return

        table = Table(title="Applications")
        table.add_column("ID", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Last Updated")

        for app in applications:
            # Look up the opportunity for company/role
            opp = get_opportunity(conn, app.opportunity_id)
            company = opp.company if opp else "Unknown"
            role = opp.title if opp else "Unknown"

            table.add_row(
                app.id[:8],
                company,
                role,
                app.status.value,
                app.updated_at.strftime("%Y-%m-%d %H:%M"),
            )

        console.print(table)
    finally:
        conn.close()


@funnel_app.command("show")
def funnel_show(
    application_id: str = typer.Argument(
        help="The application ID (or first 8 characters)."
    ),
) -> None:
    """Show full details of one application, including its interactions."""
    conn = _get_connection()
    try:
        # Try exact match first, then prefix match
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

        # Get opportunity details
        opp = get_opportunity(conn, app.opportunity_id)
        company = opp.company if opp else "Unknown"
        role = opp.title if opp else "Unknown"

        # Application detail panel
        detail_lines = [
            f"[bold]ID:[/bold]          {app.id}",
            f"[bold]Company:[/bold]     {company}",
            f"[bold]Role:[/bold]        {role}",
            f"[bold]Status:[/bold]      {app.status.value}",
            f"[bold]Created:[/bold]     {app.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"[bold]Updated:[/bold]     {app.updated_at.strftime('%Y-%m-%d %H:%M')}",
        ]

        if opp:
            if opp.location:
                detail_lines.append(f"[bold]Location:[/bold]    {opp.location}")
            if opp.salary_min or opp.salary_max:
                sal_parts: list[str] = []
                if opp.salary_min:
                    sal_parts.append(f"${opp.salary_min:,}")
                if opp.salary_max:
                    sal_parts.append(f"${opp.salary_max:,}")
                detail_lines.append(
                    f"[bold]Salary:[/bold]      {' - '.join(sal_parts)}"
                )
            if opp.source_url:
                detail_lines.append(f"[bold]URL:[/bold]         {opp.source_url}")

        console.print(
            Panel(
                "\n".join(detail_lines),
                title=f"{company} - {role}",
                border_style="blue",
            )
        )

        # Interactions
        interactions = list_interactions(conn, app.id)
        if interactions:
            int_table = Table(title="Interactions")
            int_table.add_column("Date", style="dim")
            int_table.add_column("Type", style="cyan")
            int_table.add_column("Direction")
            int_table.add_column("Channel")
            int_table.add_column("Content", max_width=50)

            for interaction in interactions:
                int_table.add_row(
                    interaction.created_at.strftime("%Y-%m-%d %H:%M"),
                    interaction.type.value,
                    interaction.direction,
                    interaction.channel,
                    (interaction.content[:47] + "...")
                    if interaction.content and len(interaction.content) > 50
                    else (interaction.content or "-"),
                )
            console.print(int_table)
        else:
            console.print("[dim]No interactions recorded yet.[/dim]")
    finally:
        conn.close()
