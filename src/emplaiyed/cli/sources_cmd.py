from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from emplaiyed.core.database import get_default_db_path, init_db
from emplaiyed.core.profile_store import get_default_profile_path, load_profile
from emplaiyed.sources import get_available_sources
from emplaiyed.sources.base import SearchQuery

logger = logging.getLogger(__name__)

sources_app = typer.Typer(
    name="sources",
    help="Manage and run job sources / scrapers.",
    no_args_is_help=True,
)

console = Console()


@sources_app.command("list")
def list_sources():
    """Show available sources and their status."""
    sources = get_available_sources()
    table = Table(title="Available Job Sources")
    table.add_column("Name", style="cyan")
    table.add_column("Class", style="green")
    table.add_column("Status", style="yellow")

    for name, source in sources.items():
        # Probe whether scrape() is implemented by checking for
        # NotImplementedError in a lightweight way.
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

    # Derive keywords and/or location from profile when not provided
    kw_list: list[str] = []
    if keywords is not None:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    else:
        kw_list, location = _derive_from_profile(kw_list, location)

    if not kw_list:
        console.print(
            "[red]No keywords provided and could not derive from profile.[/red]\n"
            "Either pass --keywords or build a profile first with: emplaiyed profile build"
        )
        raise typer.Exit(code=1)

    # If location still not set, try deriving just location from profile
    if location is None:
        location = _derive_location_from_profile()

    query = SearchQuery(
        keywords=kw_list,
        location=location,
        max_results=max_results,
    )
    logger.debug("Final query: keywords=%s, location=%s", query.keywords, query.location)

    src = available[source]
    console.print(
        f"Scanning [cyan]{source}[/cyan] for "
        f"keywords={query.keywords}, location={query.location} ..."
    )

    try:
        db_conn = init_db(get_default_db_path())
        results = asyncio.run(src.scrape_and_persist(query, db_conn))
    except NotImplementedError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1)

    if not results:
        console.print("[yellow]No new opportunities found.[/yellow]")
        db_conn.close()
        return

    console.print(f"[green]{len(results)} new opportunities found.[/green]")

    # Score opportunities against profile
    scored = _score_results(results, db_conn)
    db_conn.close()

    if scored:
        table = Table(title=f"Results from {source} (scored)")
        table.add_column("#", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Location")
        table.add_column("Score", justify="right")
        table.add_column("Why", max_width=40)

        for i, so in enumerate(scored, 1):
            score_style = "bold green" if so.score >= 80 else ("yellow" if so.score >= 50 else "dim")
            table.add_row(
                str(i),
                so.opportunity.company,
                so.opportunity.title,
                so.opportunity.location or "-",
                f"[{score_style}]{so.score}[/{score_style}]",
                so.justification,
            )
        console.print(table)
        above_70 = sum(1 for s in scored if s.score >= 70)
        console.print(
            f"\n[green]{len(scored)} opportunities scored. "
            f"{above_70} scored above 70.[/green]"
        )
    else:
        # Fallback: show unscored results
        table = Table(title=f"Results from {source}")
        table.add_column("#", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Location")
        table.add_column("URL", style="blue")

        for i, opp in enumerate(results, 1):
            table.add_row(
                str(i),
                opp.company,
                opp.title,
                opp.location or "-",
                opp.source_url or "-",
            )
        console.print(table)
        console.print(f"\n[green]{len(results)} new opportunities saved (unscored).[/green]")


def _score_results(results, db_conn):
    """Try to score results against the profile. Returns scored list or None."""
    from emplaiyed.scoring import score_opportunities

    profile_path = get_default_profile_path()
    if not profile_path.exists():
        console.print("[dim]No profile found — skipping scoring.[/dim]")
        return None

    try:
        profile = load_profile(profile_path)
    except Exception as exc:
        logger.warning("Failed to load profile for scoring: %s", exc)
        return None

    console.print("Scoring against your profile...")
    try:
        scored = asyncio.run(
            score_opportunities(profile, results, db_conn=db_conn)
        )
        return scored
    except Exception as exc:
        logger.warning("Scoring failed: %s", exc)
        console.print(f"[yellow]Scoring failed: {exc}[/yellow]")
        return None


def _derive_from_profile(
    kw_list: list[str], location: str | None
) -> tuple[list[str], str | None]:
    """Try to load the profile and derive keywords + location."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        logger.debug("No profile found at %s", profile_path)
        return kw_list, location

    try:
        profile = load_profile(profile_path)
    except Exception as exc:
        logger.warning("Failed to load profile: %s", exc)
        return kw_list, location

    # Derive keywords from target_roles + top skills
    derived: list[str] = []
    if profile.aspirations and profile.aspirations.target_roles:
        derived.extend(profile.aspirations.target_roles)
    if profile.skills:
        derived.extend(profile.skills[:5])
    if derived:
        kw_list = derived
        console.print(f"[dim]Derived keywords from profile: {', '.join(kw_list)}[/dim]")
        logger.debug("Derived keywords: %s", kw_list)

    # Derive location from geographic_preferences (skip "Remote")
    if location is None and profile.aspirations:
        for pref in profile.aspirations.geographic_preferences:
            if pref.lower().strip() != "remote":
                location = pref
                console.print(f"[dim]Derived location from profile: {location}[/dim]")
                logger.debug("Derived location: %s", location)
                break

    return kw_list, location


def _derive_location_from_profile() -> str | None:
    """Try to derive just the location from the profile."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        return None
    try:
        profile = load_profile(profile_path)
    except Exception:
        return None
    if profile.aspirations:
        for pref in profile.aspirations.geographic_preferences:
            if pref.lower().strip() != "remote":
                console.print(f"[dim]Derived location from profile: {pref}[/dim]")
                return pref
    return None


def _probe_source_status(source) -> str:
    """Return a human-readable status for a source.

    Tries to call scrape() with an empty query. If it raises
    NotImplementedError, the source is a stub.
    """
    try:
        asyncio.run(source.scrape(SearchQuery()))
        return "ready"
    except NotImplementedError:
        return "stub (not implemented)"
    except Exception:
        return "ready"
