"""CLI shared utilities — DRY helpers used across all commands."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import NoReturn

import typer
from rich.console import Console

from emplaiyed.core.database import (
    get_application,
    get_default_db_path,
    get_work_item,
    init_db,
    list_applications,
    list_work_items,
)
from emplaiyed.core.models import Profile
from emplaiyed.core.profile_store import get_default_profile_path, load_profile

console = Console()


def cli_error(message: str) -> NoReturn:
    """Print a red error message and exit with code 1."""
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)


@contextmanager
def db_connection():
    """Context manager for the default database connection."""
    conn = init_db(get_default_db_path())
    try:
        yield conn
    finally:
        conn.close()


def require_profile() -> Profile:
    """Load the profile or exit with an error message."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        cli_error("No profile found. Run `emplaiyed profile build` first.")
    return load_profile(profile_path)


def try_load_profile() -> Profile | None:
    """Load the profile, returning None on failure (no error message)."""
    profile_path = get_default_profile_path()
    if not profile_path.exists():
        return None
    try:
        return load_profile(profile_path)
    except Exception:
        return None


def resolve_application(conn: sqlite3.Connection, app_id: str):
    """Resolve an application by exact ID or prefix. Exits on ambiguous/not found."""
    app = get_application(conn, app_id)
    if app is not None:
        return app

    all_apps = list_applications(conn)
    matches = [a for a in all_apps if a.id.startswith(app_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        cli_error(f"Ambiguous ID: '{app_id}' matches {len(matches)} applications.")
    cli_error(f"Application not found: '{app_id}'")


def resolve_work_item(conn: sqlite3.Connection, item_id: str):
    """Resolve a work item by exact ID or prefix. Exits on ambiguous/not found."""
    item = get_work_item(conn, item_id)
    if item is not None:
        return item

    all_items = list_work_items(conn)
    matches = [w for w in all_items if w.id.startswith(item_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        cli_error(f"Ambiguous ID: '{item_id}' matches {len(matches)} items.")
    cli_error(f"Work item not found: '{item_id}'")
