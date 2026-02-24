"""Inbox monitor CLI commands — check, setup (launchd), history."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from textwrap import dedent

import typer
from rich.table import Table

from emplaiyed.cli import console, db_connection

inbox_app = typer.Typer(
    name="inbox",
    help="Monitor your email inbox for job-search replies.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# inbox check
# ---------------------------------------------------------------------------


@inbox_app.command()
def check(
    days: int = typer.Option(1, "--days", "-d", help="How many days back to fetch."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Classify without recording or notifying."
    ),
) -> None:
    """Fetch recent emails, classify them, and send a Telegram briefing."""
    from emplaiyed.inbox.logging_setup import configure_inbox_logging
    from emplaiyed.inbox.monitor import run_inbox_check

    log_file = configure_inbox_logging()
    console.print(f"[dim]Logging to {log_file}[/dim]")

    with db_connection() as conn:
        result = asyncio.run(run_inbox_check(conn, since_days=days, dry_run=dry_run))

    console.print(f"\n[bold]Inbox Check Results[/bold]")
    console.print(f"  Fetched:           {result.total_fetched}")
    console.print(f"  Already processed: {result.already_processed}")
    console.print(f"  Classified:        {result.classified}")
    console.print(f"  Matched to apps:   {result.matched}")
    console.print(f"  Work items:        {result.work_items_created}")
    console.print(f"  Telegram sent:     {result.notification_sent}")

    if result.errors:
        console.print(f"\n[yellow]Warnings ({len(result.errors)}):[/yellow]")
        for err in result.errors:
            console.print(f"  - {err}")

    if result.processed:
        console.print()
        table = Table(title="Processed Emails")
        table.add_column("From", max_width=25)
        table.add_column("Subject", max_width=35)
        table.add_column("Category")
        table.add_column("Urgency")
        table.add_column("Matched")
        table.add_column("Action")

        for p in result.processed:
            matched = p.match.opportunity.company if p.match else "-"
            action = "Yes" if p.classification.requires_action else "-"
            urgency_color = {
                "high": "red",
                "medium": "yellow",
                "low": "dim",
            }.get(p.classification.urgency, "")
            table.add_row(
                p.email.from_name[:25],
                p.email.subject[:35],
                p.classification.category.value,
                f"[{urgency_color}]{p.classification.urgency}[/{urgency_color}]",
                matched,
                action,
            )
        console.print(table)

    if dry_run:
        console.print("\n[yellow]Dry run — nothing was recorded or sent.[/yellow]")


# ---------------------------------------------------------------------------
# inbox history
# ---------------------------------------------------------------------------


@inbox_app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of records to show."),
) -> None:
    """Show recently processed emails."""
    from emplaiyed.core.database import list_processed_emails

    with db_connection() as conn:
        rows = list_processed_emails(conn, limit=limit)

    if not rows:
        console.print("[dim]No processed emails yet.[/dim]")
        return

    table = Table(title=f"Last {limit} Processed Emails")
    table.add_column("Processed At", max_width=20)
    table.add_column("From", max_width=25)
    table.add_column("Subject", max_width=35)
    table.add_column("Category")
    table.add_column("Matched App")

    for row in rows:
        processed_at = (row.get("processed_at") or "")[:19]
        from_addr = (row.get("from_address") or "")[:25]
        subject = (row.get("subject") or "")[:35]
        category = row.get("category") or "-"
        matched = row.get("matched_app_id") or "-"
        if matched != "-":
            matched = matched[:8]
        table.add_row(processed_at, from_addr, subject, category, matched)

    console.print(table)


# ---------------------------------------------------------------------------
# inbox setup  (launchd plist generation)
# ---------------------------------------------------------------------------

_PLIST_LABEL = "org.jpelletier.emplaiyed-inbox"
_PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
_PLIST_PATH = _PLIST_DIR / f"{_PLIST_LABEL}.plist"

_PLIST_TEMPLATE = dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>{label}</string>

        <key>ProgramArguments</key>
        <array>
            <string>{python}</string>
            <string>-m</string>
            <string>emplaiyed</string>
            <string>inbox</string>
            <string>check</string>
        </array>

        <key>StartCalendarInterval</key>
        <dict>
            <key>Hour</key>
            <integer>{hour}</integer>
            <key>Minute</key>
            <integer>{minute}</integer>
        </dict>

        <key>WorkingDirectory</key>
        <string>{workdir}</string>

        <key>EnvironmentVariables</key>
        <dict>
            <key>PATH</key>
            <string>{path_env}</string>
        </dict>

        <key>StandardOutPath</key>
        <string>{log_dir}/inbox-check.log</string>
        <key>StandardErrorPath</key>
        <string>{log_dir}/inbox-check.err</string>

        <key>RunAtLoad</key>
        <false/>
    </dict>
    </plist>
""")


@inbox_app.command()
def setup(
    hour: int = typer.Option(8, "--hour", help="Hour to run (0-23)."),
    minute: int = typer.Option(0, "--minute", help="Minute to run (0-59)."),
    uninstall: bool = typer.Option(
        False, "--uninstall", help="Remove the launchd job."
    ),
) -> None:
    """Install (or remove) a macOS launchd job to run inbox check daily."""
    if uninstall:
        if _PLIST_PATH.exists():
            os.system(f"launchctl unload '{_PLIST_PATH}' 2>/dev/null")
            _PLIST_PATH.unlink()
            console.print(f"[green]Removed[/green] {_PLIST_PATH}")
        else:
            console.print("[dim]No launchd job found.[/dim]")
        return

    # Find the project root for WorkingDirectory
    from emplaiyed.core.paths import find_project_root

    project_root = find_project_root()
    log_dir = project_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist_content = _PLIST_TEMPLATE.format(
        label=_PLIST_LABEL,
        python=sys.executable,
        hour=hour,
        minute=minute,
        workdir=project_root,
        path_env=os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        log_dir=log_dir,
    )

    _PLIST_DIR.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.write_text(plist_content)
    console.print(f"[green]Written[/green] {_PLIST_PATH}")

    # Load the job
    os.system(f"launchctl unload '{_PLIST_PATH}' 2>/dev/null")
    ret = os.system(f"launchctl load '{_PLIST_PATH}'")
    if ret == 0:
        console.print(
            f"[green]Loaded![/green] Inbox check will run daily at "
            f"{hour:02d}:{minute:02d}."
        )
        console.print(
            f"  Logs: {log_dir}/inbox-check.log\n  Errors: {log_dir}/inbox-check.err"
        )
    else:
        console.print("[red]Failed to load launchd job.[/red]")
