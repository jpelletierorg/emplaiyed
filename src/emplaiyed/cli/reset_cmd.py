"""Reset command — wipe the database and generated assets to start fresh."""

from __future__ import annotations

import shutil

import typer

from emplaiyed.cli import console
from emplaiyed.core.database import get_default_db_path
from emplaiyed.core.paths import find_project_root


def reset_command(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt."),
) -> None:
    """Delete the database and all generated assets to start fresh."""
    db_path = get_default_db_path()
    assets_dir = find_project_root() / "data" / "assets"

    if not force:
        console.print("[yellow]This will delete:[/yellow]")
        console.print(f"  Database: {db_path}")
        console.print(f"  Assets:   {assets_dir}")
        confirm = typer.confirm("\nAre you sure?")
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()

    deleted = []
    if db_path.exists():
        db_path.unlink()
        deleted.append("database")

    if assets_dir.exists():
        shutil.rmtree(assets_dir)
        deleted.append("assets")

    if deleted:
        console.print(f"[green]Deleted {' + '.join(deleted)}. Fresh start![/green]")
    else:
        console.print("[dim]Nothing to delete — already clean.[/dim]")
