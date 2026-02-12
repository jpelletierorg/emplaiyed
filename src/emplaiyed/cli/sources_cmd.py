"""Sources CLI — scan job boards and score opportunities."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer
from rich.table import Table

from emplaiyed.cli import console, try_load_profile
from emplaiyed.core.database import get_default_db_path, init_db, list_applications
from emplaiyed.core.models import ApplicationStatus
from emplaiyed.sources import get_available_sources
from emplaiyed.sources.base import SearchQuery

logger = logging.getLogger(__name__)

sources_app = typer.Typer(
    name="sources",
    help="Manage and run job sources / scrapers.",
    no_args_is_help=True,
)


@sources_app.command("list")
def list_sources():
    """Show available sources and their status."""
    sources = get_available_sources()
    table = Table(title="Available Job Sources")
    table.add_column("Name", style="cyan")
    table.add_column("Class", style="green")
    table.add_column("Status", style="yellow")

    for name, source in sources.items():
        status = _probe_source_status(source)
        table.add_row(name, type(source).__name__, status)

    console.print(table)


@sources_app.command("scan")
def scan(
    source: str = typer.Option(..., "--source", "-s", help="Source name to scan."),
    keywords: Optional[str] = typer.Option(
        None, "--keywords", "-k", help="Comma-separated keywords (derived from profile if omitted)."
    ),
    location: Optional[str] = typer.Option(
        None, "--location", "-l", help="Location filter (derived from profile if omitted)."
    ),
    max_results: int = typer.Option(50, "--max-results", "-n", help="Max results."),
):
    """Run a scraper and show results."""
    available = get_available_sources()
    if source not in available:
        console.print(
            f"[red]Unknown source '{source}'. "
            f"Available: {', '.join(available.keys())}[/red]"
        )
        raise typer.Exit(code=1)

    profile = try_load_profile()

    # Derive keywords and/or location from profile when not provided
    kw_list: list[str] = []
    if keywords is not None:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    elif profile:
        kw_list, location = _derive_from_profile(profile, location)

    if not kw_list:
        console.print(
            "[red]No keywords provided and could not derive from profile.[/red]\n"
            "Either pass --keywords or build a profile first with: emplaiyed profile build"
        )
        raise typer.Exit(code=1)

    # If location still not set, try deriving from profile
    if location is None and profile and profile.aspirations:
        for pref in profile.aspirations.geographic_preferences:
            if pref.lower().strip() != "remote":
                location = pref
                console.print(f"[dim]Derived location from profile: {location}[/dim]")
                break

    query = SearchQuery(keywords=kw_list, location=location, max_results=max_results)

    src = available[source]
    console.print(
        f"Scanning [cyan]{source}[/cyan] for "
        f"keywords={query.keywords}, location={query.location} ..."
    )

    db_conn = init_db(get_default_db_path())
    try:
        try:
            results = asyncio.run(src.scrape_and_persist(query, db_conn))
        except NotImplementedError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
            raise typer.Exit(code=1)

        if not results:
            console.print("[yellow]No new opportunities found.[/yellow]")
            return

        console.print(f"[green]{len(results)} new opportunities found.[/green]")

        # Score + eager asset generation
        scored = _score_results(profile, results, db_conn)

        if scored:
            asset_count = _eager_generate_assets(profile, scored, db_conn)
            _show_scored_table(source, scored, db_conn, asset_count)
        else:
            _show_unscored_table(source, results)
    finally:
        db_conn.close()


def _score_results(profile, results, db_conn):
    """Try to score results against the profile. Returns scored list or None."""
    if profile is None:
        console.print("[dim]No profile found — skipping scoring.[/dim]")
        return None

    from emplaiyed.scoring import score_opportunities

    console.print("Scoring against your profile...")
    try:
        return asyncio.run(score_opportunities(profile, results, db_conn=db_conn))
    except Exception as exc:
        logger.warning("Scoring failed: %s", exc)
        console.print(f"[yellow]Scoring failed: {exc}[/yellow]")
        return None


def _eager_generate_assets(profile, scored, db_conn) -> int:
    """Generate assets for top N scored opportunities. Returns count created."""
    if profile is None:
        return 0

    from emplaiyed.generation.pipeline import generate_assets_batch

    apps = list_applications(db_conn, status=ApplicationStatus.SCORED)
    opp_to_app = {a.opportunity_id: a.id for a in apps}

    scored_apps = [
        (opp_to_app[so.opportunity.id], so.opportunity)
        for so in scored
        if so.opportunity.id in opp_to_app
    ]

    if not scored_apps:
        return 0

    console.print("Generating assets for top opportunities...")
    try:
        results = asyncio.run(generate_assets_batch(db_conn, profile, scored_apps))
        return len(results)
    except Exception as exc:
        logger.warning("Asset generation failed: %s", exc)
        console.print(f"[yellow]Asset generation failed: {exc}[/yellow]")
        return 0


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "\u2026"


def _show_scored_table(source, scored, db_conn, asset_count):
    """Display scored results table."""
    apps = list_applications(db_conn, status=ApplicationStatus.OUTREACH_PENDING)
    asset_opp_ids = {a.opportunity_id for a in apps}
    has_assets = bool(asset_opp_ids)

    table = Table(title=f"Results from {source} (scored)")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", width=5)
    table.add_column("Company", style="cyan", max_width=20)
    table.add_column("Title", style="green", max_width=25)
    table.add_column("Location", max_width=15)
    table.add_column("Why")
    if has_assets:
        table.add_column("Assets", justify="center", width=6)

    for i, so in enumerate(scored, 1):
        score_style = "bold green" if so.score >= 80 else ("yellow" if so.score >= 50 else "dim")
        loc = _truncate(so.opportunity.location, 20) if so.opportunity.location else "-"
        row = [
            str(i),
            f"[{score_style}]{so.score}[/{score_style}]",
            so.opportunity.company,
            so.opportunity.title,
            loc,
            _truncate(so.justification, 80),
        ]
        if has_assets:
            row.append("Y" if so.opportunity.id in asset_opp_ids else "")
        table.add_row(*row)

    console.print(table)
    above_70 = sum(1 for s in scored if s.score >= 70)
    console.print(
        f"\n[green]{len(scored)} opportunities scored. {above_70} scored above 70.[/green]"
    )
    if asset_count:
        console.print(
            f"[blue]{asset_count} work items created with generated assets.[/blue] "
            f"Run `emplaiyed work list` to review."
        )


def _show_unscored_table(source, results):
    """Display unscored results table."""
    table = Table(title=f"Results from {source}")
    table.add_column("#", style="dim")
    table.add_column("Company", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Location")
    table.add_column("URL", style="blue")

    for i, opp in enumerate(results, 1):
        table.add_row(str(i), opp.company, opp.title, opp.location or "-", opp.source_url or "-")

    console.print(table)
    console.print(f"\n[green]{len(results)} new opportunities saved (unscored).[/green]")


def _derive_from_profile(profile, location):
    """Derive keywords + location from a loaded profile."""
    kw_list: list[str] = []
    if profile.aspirations and profile.aspirations.target_roles:
        kw_list.extend(profile.aspirations.target_roles)
    if profile.skills:
        kw_list.extend(profile.skills[:5])
    if kw_list:
        console.print(f"[dim]Derived keywords from profile: {', '.join(kw_list)}[/dim]")

    if location is None and profile.aspirations:
        for pref in profile.aspirations.geographic_preferences:
            if pref.lower().strip() != "remote":
                location = pref
                console.print(f"[dim]Derived location from profile: {location}[/dim]")
                break

    return kw_list, location


def _probe_source_status(source) -> str:
    """Return a human-readable status for a source."""
    try:
        asyncio.run(source.scrape(SearchQuery()))
        return "ready"
    except NotImplementedError:
        return "stub (not implemented)"
    except Exception:
        return "ready"
