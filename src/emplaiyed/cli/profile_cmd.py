"""Profile management CLI commands."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from emplaiyed.core.profile_store import get_default_profile_path, load_profile

profile_app = typer.Typer(
    name="profile",
    help="Manage your professional profile.",
    no_args_is_help=True,
)

console = Console()


@profile_app.command("show")
def profile_show() -> None:
    """Load and display your profile from the default YAML path."""
    path = get_default_profile_path()

    if not path.exists():
        console.print(
            Panel(
                f"No profile found at [bold]{path}[/bold].\n\n"
                "Run [bold green]emplaiyed profile build[/bold green] to create one.",
                title="No Profile",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    try:
        profile = load_profile(path)
    except Exception as exc:
        console.print(f"[red]Error loading profile:[/red] {exc}")
        raise typer.Exit(code=1)

    # -- Header --
    console.print(
        Panel(
            f"[bold]{profile.name}[/bold]\n"
            f"{profile.email}"
            + (f"  |  {profile.phone}" if profile.phone else ""),
            title="Profile",
            border_style="blue",
        )
    )

    # -- Skills --
    if profile.skills:
        console.print(
            Panel(", ".join(profile.skills), title="Skills", border_style="green")
        )

    # -- Languages --
    if profile.languages:
        lang_table = Table(title="Languages")
        lang_table.add_column("Language", style="cyan")
        lang_table.add_column("Proficiency")
        for lang in profile.languages:
            lang_table.add_row(lang.language, lang.proficiency)
        console.print(lang_table)

    # -- Education --
    if profile.education:
        edu_table = Table(title="Education")
        edu_table.add_column("Institution", style="cyan")
        edu_table.add_column("Degree")
        edu_table.add_column("Field")
        edu_table.add_column("Start")
        edu_table.add_column("End")
        for edu in profile.education:
            edu_table.add_row(
                edu.institution,
                edu.degree,
                edu.field,
                str(edu.start_date) if edu.start_date else "-",
                str(edu.end_date) if edu.end_date else "-",
            )
        console.print(edu_table)

    # -- Employment History --
    if profile.employment_history:
        emp_table = Table(title="Employment History")
        emp_table.add_column("Company", style="cyan")
        emp_table.add_column("Title")
        emp_table.add_column("Start")
        emp_table.add_column("End")
        emp_table.add_column("Description")
        for emp in profile.employment_history:
            emp_table.add_row(
                emp.company,
                emp.title,
                str(emp.start_date) if emp.start_date else "-",
                str(emp.end_date) if emp.end_date else "Present",
                emp.description or "-",
            )
            if emp.highlights:
                for hl in emp.highlights:
                    emp_table.add_row("", "", "", "", f"  - {hl}")
        console.print(emp_table)

    # -- Certifications --
    if profile.certifications:
        cert_table = Table(title="Certifications")
        cert_table.add_column("Name", style="cyan")
        cert_table.add_column("Issuer")
        cert_table.add_column("Date")
        for cert in profile.certifications:
            cert_table.add_row(
                cert.name,
                cert.issuer,
                str(cert.date_obtained) if cert.date_obtained else "-",
            )
        console.print(cert_table)

    # -- Aspirations --
    if profile.aspirations:
        asp = profile.aspirations
        lines: list[str] = []
        if asp.target_roles:
            lines.append(f"[bold]Target Roles:[/bold] {', '.join(asp.target_roles)}")
        if asp.target_industries:
            lines.append(
                f"[bold]Industries:[/bold] {', '.join(asp.target_industries)}"
            )
        if asp.salary_minimum or asp.salary_target:
            sal_parts: list[str] = []
            if asp.salary_minimum:
                sal_parts.append(f"min ${asp.salary_minimum:,}")
            if asp.salary_target:
                sal_parts.append(f"target ${asp.salary_target:,}")
            lines.append(f"[bold]Salary:[/bold] {' / '.join(sal_parts)}")
        if asp.urgency:
            lines.append(f"[bold]Urgency:[/bold] {asp.urgency}")
        if asp.geographic_preferences:
            lines.append(
                f"[bold]Location:[/bold] {', '.join(asp.geographic_preferences)}"
            )
        if asp.work_arrangement:
            lines.append(f"[bold]Arrangement:[/bold] {', '.join(asp.work_arrangement)}")
        if asp.statement:
            lines.append(f"\n{asp.statement}")
        console.print(
            Panel("\n".join(lines), title="Aspirations", border_style="magenta")
        )


@profile_app.command("path")
def profile_path() -> None:
    """Print the path to the profile YAML file."""
    path = get_default_profile_path()
    console.print(str(path))


# ---------------------------------------------------------------------------
# profile build
# ---------------------------------------------------------------------------

def _rich_prompt(message: str) -> str:
    """Prompt the user using rich's console and return their input."""
    return console.input(f"[bold cyan]{message}[/bold cyan]\n> ")


def _rich_print(message: str) -> None:
    """Print a message using rich's console."""
    console.print(message)


@profile_app.command("build")
def profile_build() -> None:
    """Interactively build or update your job seeker profile."""
    from emplaiyed.profile.builder import build_profile

    try:
        asyncio.run(
            build_profile(
                prompt_fn=_rich_prompt,
                print_fn=_rich_print,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Profile build cancelled.[/yellow]")
        raise typer.Exit(code=0)
