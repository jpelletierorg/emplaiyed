"""Funnel / application tracking CLI commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from emplaiyed.cli import console, db_connection, resolve_application
from emplaiyed.core.database import get_opportunity, list_applications, list_interactions
from emplaiyed.core.models import ApplicationStatus

funnel_app = typer.Typer(
    name="funnel",
    help="View and manage your application funnel.",
    no_args_is_help=True,
)


@funnel_app.command("status")
def funnel_status() -> None:
    """Show a summary of how many applications are in each pipeline stage."""
    with db_connection() as conn:
        applications = list_applications(conn)

        if not applications:
            console.print(Panel(
                "No applications tracked yet.\n\n"
                "Add opportunities and start applying to see your funnel here.",
                title="Funnel Status",
                border_style="yellow",
            ))
            return

        counts: dict[str, int] = {s.value: 0 for s in ApplicationStatus}
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


@funnel_app.command("list")
def funnel_list(
    stage: Optional[str] = typer.Option(
        None, "--stage", "-s",
        help="Filter by application stage (e.g. SCORED, OUTREACH_SENT).",
    ),
) -> None:
    """List all applications, optionally filtered by stage."""
    with db_connection() as conn:
        filters = {}
        if stage:
            try:
                status_enum = ApplicationStatus(stage.upper())
            except ValueError:
                valid = ", ".join(s.value for s in ApplicationStatus)
                console.print(f"[red]Invalid stage:[/red] {stage}\nValid stages: {valid}")
                raise typer.Exit(code=1)
            filters["status"] = status_enum

        applications = list_applications(conn, **filters)

        if not applications:
            msg = f"No applications with stage [bold]{stage.upper()}[/bold]." if stage else "No applications tracked yet."
            console.print(msg if stage else Panel(msg, title="Applications", border_style="yellow"))
            return

        table = Table(title="Applications")
        table.add_column("ID", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Last Updated")

        for app in applications:
            opp = get_opportunity(conn, app.opportunity_id)
            table.add_row(
                app.id[:8],
                opp.company if opp else "Unknown",
                opp.title if opp else "Unknown",
                app.status.value,
                app.updated_at.strftime("%Y-%m-%d %H:%M"),
            )

        console.print(table)


@funnel_app.command("show")
def funnel_show(
    application_id: str = typer.Argument(help="The application ID (or first 8 characters)."),
) -> None:
    """Show full details of one application, including its interactions."""
    with db_connection() as conn:
        app = resolve_application(conn, application_id)
        opp = get_opportunity(conn, app.opportunity_id)
        company = opp.company if opp else "Unknown"
        role = opp.title if opp else "Unknown"

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
                sal_parts = [f"${v:,}" for v in [opp.salary_min, opp.salary_max] if v]
                detail_lines.append(f"[bold]Salary:[/bold]      {' - '.join(sal_parts)}")
            if opp.source_url:
                detail_lines.append(f"[bold]URL:[/bold]         {opp.source_url}")

        console.print(Panel(
            "\n".join(detail_lines),
            title=f"{company} - {role}",
            border_style="blue",
        ))

        interactions = list_interactions(conn, app.id)
        if interactions:
            int_table = Table(title="Interactions")
            int_table.add_column("Date", style="dim")
            int_table.add_column("Type", style="cyan")
            int_table.add_column("Direction")
            int_table.add_column("Channel")
            int_table.add_column("Content", max_width=50)

            for interaction in interactions:
                content = interaction.content or "-"
                if interaction.content and len(interaction.content) > 50:
                    content = interaction.content[:47] + "..."
                int_table.add_row(
                    interaction.created_at.strftime("%Y-%m-%d %H:%M"),
                    interaction.type.value,
                    interaction.direction,
                    interaction.channel,
                    content,
                )
            console.print(int_table)
        else:
            console.print("[dim]No interactions recorded yet.[/dim]")
