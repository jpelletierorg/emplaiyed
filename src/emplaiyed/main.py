import logging
from importlib.metadata import version as pkg_version
from typing import Optional

import typer

from emplaiyed.cli.followup_cmd import followup_command
from emplaiyed.cli.funnel_cmd import funnel_app
from emplaiyed.cli.negotiate_cmd import accept_command, negotiate_command, offers_command
from emplaiyed.cli.outreach_cmd import outreach_command
from emplaiyed.cli.prep_cmd import prep_command
from emplaiyed.cli.profile_cmd import profile_app
from emplaiyed.cli.schedule_cmd import calendar_command, schedule_command
from emplaiyed.cli.sources_cmd import sources_app

app = typer.Typer(
    name="emplaiyed",
    help="AI-powered job seeking toolkit.",
    no_args_is_help=True,
    invoke_without_command=True,
)

app.add_typer(profile_app, name="profile")
app.add_typer(funnel_app, name="funnel")
app.add_typer(sources_app, name="sources")

app.command("schedule")(schedule_command)
app.command("calendar")(calendar_command)
app.command("outreach")(outreach_command)
app.command("followup")(followup_command)
app.command("prep")(prep_command)
app.command("negotiate")(negotiate_command)
app.command("accept")(accept_command)
app.command("offers")(offers_command)


def version_callback(value: bool):
    if value:
        typer.echo(f"emplaiyed {pkg_version('emplaiyed')}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Enable debug logging.",
    ),
):
    """AI-powered job seeking toolkit."""
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s: %(message)s")
    logging.getLogger("emplaiyed").setLevel(level)


if __name__ == "__main__":
    app()
