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


def _show_scored_table(source, scored, db_conn, asset_count):
    """Display scored results summary."""
    above_70 = sum(1 for s in scored if s.score >= 70)
    console.print(
        f"\n[green]{len(scored)} opportunities scored. {above_70} scored above 70.[/green]"
    )
    if asset_count:
        console.print(
            f"[blue]{asset_count} sets of assets generated.[/blue]"
        )
    console.print("Run [cyan]emplaiyed console[/cyan] to review and manage them.")


def _show_unscored_table(source, results):
    """Display unscored results summary."""
    console.print(f"\n[green]{len(results)} new opportunities saved (unscored).[/green]")
    console.print("Run [cyan]emplaiyed console[/cyan] to review and manage them.")


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


@sources_app.command("search")
def search(
    direction: Optional[str] = typer.Argument(
        None, help="Steer the search, e.g. 'find me ML research roles for an applied AI engineer'."
    ),
    max_results: int = typer.Option(50, "--max-results", "-n", help="Target number of opportunities."),
    time_limit: int = typer.Option(300, "--time", "-t", help="Max search duration in seconds (default: 300 = 5min)."),
):
    """Agentic search — AI finds jobs across all sources automatically.

    Optionally pass a direction to steer the search:
        emplaiyed sources search "find me applied AI engineer roles building agents"
    """
    from emplaiyed.sources.search_agent import agentic_search

    profile = try_load_profile()
    if not profile:
        console.print(
            "[red]Profile required for agentic search.[/red]\n"
            "Build one first with: emplaiyed profile build"
        )
        raise typer.Exit(code=1)

    sources = get_available_sources()

    def _progress(msg: str) -> None:
        console.print(f"  [dim]{msg}[/dim]")

    db_conn = init_db(get_default_db_path())
    try:
        result = asyncio.run(
            agentic_search(
                profile, sources, direction=direction,
                time_limit=time_limit,
                db_conn=db_conn, on_progress=_progress,
            )
        )

        if not result.opportunities:
            console.print("[yellow]No opportunities found.[/yellow]")
            return

        # Opportunities are already persisted as they're found by the agent.
        console.print(
            f"\n[green]{len(result.opportunities)} opportunities found "
            f"and saved to database.[/green]"
        )
        console.print(f"[dim]Queries used: {len(result.queries_used)}[/dim]")
        console.print(f"[dim]Summary: {result.summary}[/dim]")

        # Score if possible
        scored = _score_results(profile, result.opportunities, db_conn)
        if scored:
            asset_count = _eager_generate_assets(profile, scored, db_conn)
            _show_scored_table("agentic", scored, db_conn, asset_count)
        else:
            console.print("\nRun [cyan]emplaiyed console[/cyan] to review.")
    finally:
        db_conn.close()


def _probe_source_status(source) -> str:
    """Return a human-readable status for a source."""
    try:
        asyncio.run(source.scrape(SearchQuery()))
        return "ready"
    except NotImplementedError:
        return "stub (not implemented)"
    except Exception:
        return "ready"
