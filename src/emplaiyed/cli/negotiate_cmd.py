"""Negotiate and accept CLI commands."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel

from emplaiyed.core.database import (
    get_application,
    get_default_db_path,
    get_opportunity,
    init_db,
    list_applications,
    list_offers,
    save_interaction,
    save_offer,
)
from emplaiyed.core.models import (
    ApplicationStatus,
    Interaction,
    InteractionType,
    Offer,
    OfferStatus,
)
from emplaiyed.core.profile_store import get_default_profile_path, load_profile
from emplaiyed.negotiation import generate_negotiation
from emplaiyed.tracker.state_machine import transition

logger = logging.getLogger(__name__)
console = Console()


def _resolve_app(conn, application_id: str):
    """Resolve an application by ID or prefix."""
    app = get_application(conn, application_id)
    if app is None:
        all_apps = list_applications(conn)
        matches = [a for a in all_apps if a.id.startswith(application_id)]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            console.print(
                f"[red]Ambiguous ID:[/red] '{application_id}' matches {len(matches)} apps."
            )
            raise typer.Exit(code=1)
    if app is None:
        console.print(f"[red]Application not found:[/red] '{application_id}'")
        raise typer.Exit(code=1)
    return app


def offers_command() -> None:
    """List all pending offers."""
    conn = init_db(get_default_db_path())
    try:
        offers = list_offers(conn)
        if not offers:
            console.print("[yellow]No offers recorded.[/yellow]")
            return

        from rich.table import Table

        table = Table(title="Offers")
        table.add_column("Company")
        table.add_column("Role")
        table.add_column("Salary", justify="right")
        table.add_column("Deadline")
        table.add_column("Status")

        for offer in offers:
            app = get_application(conn, offer.application_id)
            opp = get_opportunity(conn, app.opportunity_id) if app else None
            company = opp.company if opp else "Unknown"
            role = opp.title if opp else "Unknown"
            salary = f"${offer.salary:,}" if offer.salary else "-"
            deadline = str(offer.deadline) if offer.deadline else "-"
            table.add_row(company, role, salary, deadline, offer.status.value)

        console.print(table)
    finally:
        conn.close()


def negotiate_command(
    application_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Generate a negotiation strategy for an offer."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        console.print("[red]No profile found.[/red]")
        raise typer.Exit(code=1)

    profile = load_profile(profile_path)
    conn = init_db(get_default_db_path())

    try:
        app = _resolve_app(conn, application_id)
        opp = get_opportunity(conn, app.opportunity_id)
        if opp is None:
            console.print("[red]Opportunity not found.[/red]")
            raise typer.Exit(code=1)

        # Find the offer for this application
        offers = list_offers(conn, application_id=app.id)
        if not offers:
            console.print("[red]No offer found for this application.[/red]")
            raise typer.Exit(code=1)

        offer = offers[0]

        console.print(
            f"\nNegotiating: [bold]{opp.company}[/bold] — {opp.title}\n"
            f"Offered: ${offer.salary:,}\n"
        )

        try:
            strategy = asyncio.run(generate_negotiation(profile, opp, offer))
        except Exception as exc:
            console.print(f"[red]Strategy generation failed: {exc}[/red]")
            raise typer.Exit(code=1)

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

        # Transition to NEGOTIATING
        if app.status == ApplicationStatus.OFFER_RECEIVED:
            transition(conn, app.id, ApplicationStatus.NEGOTIATING)

        # Record the counter email as an interaction
        interaction = Interaction(
            application_id=app.id,
            type=InteractionType.EMAIL_SENT,
            direction="outbound",
            channel="email",
            content=f"Subject: {strategy.counter_email_subject}\n\n{strategy.counter_email_body}",
            created_at=datetime.now(),
        )
        save_interaction(conn, interaction)
        console.print("[green]Counter-offer recorded.[/green]")
    finally:
        conn.close()


def accept_command(
    application_id: str = typer.Argument(help="Application ID (or prefix)."),
) -> None:
    """Accept an offer and generate an acceptance email."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        console.print("[red]No profile found.[/red]")
        raise typer.Exit(code=1)

    profile = load_profile(profile_path)
    conn = init_db(get_default_db_path())

    try:
        app = _resolve_app(conn, application_id)
        opp = get_opportunity(conn, app.opportunity_id)
        if opp is None:
            console.print("[red]Opportunity not found.[/red]")
            raise typer.Exit(code=1)

        offers = list_offers(conn, application_id=app.id)
        if not offers:
            console.print("[red]No offer found for this application.[/red]")
            raise typer.Exit(code=1)

        offer = offers[0]
        salary_str = f"${offer.salary:,}" if offer.salary else "the agreed compensation"

        console.print(
            f"\nAccepting: [bold]{opp.company}[/bold] — {opp.title} at {salary_str}\n"
        )

        # Generate acceptance email
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

        console.print(Panel(body, title="Acceptance Email", border_style="green"))

        # Transition to ACCEPTED
        transition(conn, app.id, ApplicationStatus.ACCEPTED)

        # Update offer status
        updated_offer = offer.model_copy(update={"status": OfferStatus.ACCEPTED})
        save_offer(conn, updated_offer)

        # Record the acceptance
        interaction = Interaction(
            application_id=app.id,
            type=InteractionType.EMAIL_SENT,
            direction="outbound",
            channel="email",
            content=f"Subject: Acceptance — {opp.title}\n\n{body}",
            created_at=datetime.now(),
        )
        save_interaction(conn, interaction)

        console.print("[green]Offer accepted![/green]")

        # Show stats
        all_apps = list_applications(conn)
        console.print(
            f"\nFinal stats:\n"
            f"  Applications tracked: {len(all_apps)}\n"
            f"  Accepted salary: {salary_str}\n"
        )
    finally:
        conn.close()
