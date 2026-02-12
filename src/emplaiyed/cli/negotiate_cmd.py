"""Negotiate and accept CLI commands."""

from __future__ import annotations

import asyncio

import typer
from rich.panel import Panel
from rich.table import Table

from emplaiyed.cli import cli_error, console, db_connection, require_profile, resolve_application
from emplaiyed.core.database import get_application, get_opportunity, list_offers
from emplaiyed.core.models import ApplicationStatus, WorkType
from emplaiyed.negotiation import generate_negotiation
from emplaiyed.work.queue import create_work_item


def offers_command() -> None:
    """List all pending offers."""
    with db_connection() as conn:
        offers = list_offers(conn)
        if not offers:
            console.print("[yellow]No offers recorded.[/yellow]")
            return

        table = Table(title="Offers")
        table.add_column("Company")
        table.add_column("Role")
        table.add_column("Salary", justify="right")
        table.add_column("Deadline")
        table.add_column("Status")

        for offer in offers:
            app = get_application(conn, offer.application_id)
            opp = get_opportunity(conn, app.opportunity_id) if app else None
            table.add_row(
                opp.company if opp else "Unknown",
                opp.title if opp else "Unknown",
                f"${offer.salary:,}" if offer.salary else "-",
                str(offer.deadline) if offer.deadline else "-",
                offer.status.value,
            )

        console.print(table)


def negotiate_command(
    application_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Generate a negotiation strategy for an offer."""
    profile = require_profile()

    with db_connection() as conn:
        app = resolve_application(conn, application_id)
        opp = get_opportunity(conn, app.opportunity_id)
        if opp is None:
            cli_error("Opportunity not found.")

        offers = list_offers(conn, application_id=app.id)
        if not offers:
            cli_error("No offer found for this application.")

        offer = offers[0]

        console.print(
            f"\nNegotiating: [bold]{opp.company}[/bold] — {opp.title}\n"
            f"Offered: ${offer.salary:,}\n"
        )

        try:
            strategy = asyncio.run(generate_negotiation(profile, opp, offer))
        except Exception as exc:
            cli_error(f"Strategy generation failed: {exc}")

        lines = [
            f"[bold]Analysis:[/bold] {strategy.analysis}\n",
            f"[bold]Recommended counter:[/bold] ${strategy.recommended_counter:,}\n",
            f"[bold]Counter email:[/bold]",
            f"  Subject: {strategy.counter_email_subject}",
            f"  {strategy.counter_email_body}\n",
        ]
        if strategy.risks:
            lines.append("[bold]Risks:[/bold]")
            for r in strategy.risks:
                lines.append(f"  ! {r}")

        console.print(Panel("\n".join(lines), title="Negotiation Strategy", border_style="yellow"))

        draft_text = f"Subject: {strategy.counter_email_subject}\n\n{strategy.counter_email_body}"
        instructions = (
            f"## Send counter-offer to {opp.company} — {opp.title}\n\n"
            f"**Company:** {opp.company}\n"
            f"**Role:** {opp.title}\n"
            f"**Current offer:** ${offer.salary:,}\n"
            f"**Recommended counter:** ${strategy.recommended_counter:,}\n\n"
            f"### What to do\n"
            f"1. Copy the counter-offer email below\n"
            f"2. Reply to the offer thread or send to the hiring contact\n"
            f"3. Run: `emplaiyed work done <id>`\n\n"
            f"### Draft email\n\n{draft_text}"
        )

        item = create_work_item(
            conn,
            application_id=app.id,
            work_type=WorkType.NEGOTIATE,
            title=f"Send counter-offer to {opp.company} — {opp.title}",
            instructions=instructions,
            draft_content=draft_text,
            target_status=ApplicationStatus.NEGOTIATING,
            previous_status=app.status,
            pending_status=ApplicationStatus.NEGOTIATION_PENDING,
        )
        console.print(
            f"[blue]Work item created:[/blue] {item.id[:8]}\n"
            f"Run `emplaiyed work next` to review and send."
        )


def accept_command(
    application_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Accept an offer and generate an acceptance email."""
    profile = require_profile()

    with db_connection() as conn:
        app = resolve_application(conn, application_id)
        opp = get_opportunity(conn, app.opportunity_id)
        if opp is None:
            cli_error("Opportunity not found.")

        offers = list_offers(conn, application_id=app.id)
        if not offers:
            cli_error("No offer found for this application.")

        offer = offers[0]
        salary_str = f"${offer.salary:,}" if offer.salary else "the agreed compensation"

        console.print(
            f"\nAccepting: [bold]{opp.company}[/bold] — {opp.title} at {salary_str}\n"
        )

        body = (
            f"Dear Hiring Team,\n\n"
            f"I'm thrilled to formally accept the offer for the {opp.title} "
            f"position at {opp.company} at the agreed compensation of {salary_str}.\n\n"
            f"I'm looking forward to contributing to the team. Please let me know "
            f"if there's any paperwork or onboarding steps I should complete "
            f"before my start date.\n\n"
            f"Thank you for the opportunity.\n\n"
            f"Best regards,\n{profile.name}"
        )

        draft_text = f"Subject: Acceptance — {opp.title}\n\n{body}"
        console.print(Panel(body, title="Acceptance Email", border_style="green"))

        instructions = (
            f"## Accept offer from {opp.company} — {opp.title}\n\n"
            f"**Company:** {opp.company}\n"
            f"**Role:** {opp.title}\n"
            f"**Salary:** {salary_str}\n\n"
            f"### What to do\n"
            f"1. Copy the acceptance email below\n"
            f"2. Send to the hiring contact\n"
            f"3. Run: `emplaiyed work done <id>`\n\n"
            f"### Draft email\n\n{draft_text}"
        )

        item = create_work_item(
            conn,
            application_id=app.id,
            work_type=WorkType.ACCEPT,
            title=f"Accept offer from {opp.company} — {opp.title}",
            instructions=instructions,
            draft_content=draft_text,
            target_status=ApplicationStatus.ACCEPTED,
            previous_status=app.status,
            pending_status=ApplicationStatus.ACCEPTANCE_PENDING,
        )
        console.print(
            f"[blue]Work item created:[/blue] {item.id[:8]}\n"
            f"Run `emplaiyed work next` to review and send."
        )
