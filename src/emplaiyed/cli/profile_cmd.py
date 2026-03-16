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
            f"{profile.email}" + (f"  |  {profile.phone}" if profile.phone else ""),
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
            lines.append(f"[bold]Industries:[/bold] {', '.join(asp.target_industries)}")
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


@profile_app.command("advisor")
def profile_advisor() -> None:
    """Analyze your profile against market demand and get improvement recommendations."""
    from emplaiyed.core.database import get_default_db_path, init_db
    from emplaiyed.profile.market_advisor import analyze_market_gaps

    path = get_default_profile_path()
    if not path.exists():
        console.print(
            Panel(
                f"No profile found at [bold]{path}[/bold].\n\n"
                "Run [bold green]emplaiyed profile build[/bold green] first.",
                title="No Profile",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    profile = load_profile(path)
    db_path = get_default_db_path()
    if not db_path.exists():
        console.print(
            Panel(
                "No database found. Run a search first:\n"
                "[bold green]emplaiyed sources search[/bold green]",
                title="No Data",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    conn = init_db(db_path)

    console.print(
        "\n[bold cyan]Analyzing your profile against market demand...[/bold cyan]\n"
    )

    try:
        report = asyncio.run(analyze_market_gaps(profile, conn))
    finally:
        conn.close()

    # --- Display report ---

    # Summary
    console.print(
        Panel(report.summary, title="Market Gap Analysis", border_style="blue")
    )

    # Strengths
    if report.strengths:
        strength_text = "\n".join(
            f"  [green]\u2713[/green] {s}" for s in report.strengths
        )
        console.print(
            Panel(strength_text, title="Your Strengths", border_style="green")
        )

    # Skill gaps
    if report.skill_gaps:
        gap_table = Table(title="Skill Gaps")
        gap_table.add_column("Priority", style="bold")
        gap_table.add_column("Skill", style="cyan")
        gap_table.add_column("Market Signal")
        gap_table.add_column("Recommendation")
        for g in sorted(
            report.skill_gaps,
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.priority, 3),
        ):
            priority_style = {"high": "red", "medium": "yellow", "low": "dim"}.get(
                g.priority, ""
            )
            gap_table.add_row(
                f"[{priority_style}]{g.priority.upper()}[/{priority_style}]",
                g.skill,
                g.demand_signal,
                g.recommendation,
            )
        console.print(gap_table)

    # Experience gaps
    if report.experience_gaps:
        exp_table = Table(title="Experience Gaps")
        exp_table.add_column("Area", style="cyan")
        exp_table.add_column("Market Expects")
        exp_table.add_column("You Have")
        exp_table.add_column("Action")
        for eg in report.experience_gaps:
            exp_table.add_row(
                eg.area, eg.market_expectation, eg.candidate_status, eg.recommendation
            )
        console.print(exp_table)

    # Project suggestions
    if report.project_suggestions:
        console.print("\n[bold]Suggested Projects to Build[/bold]")
        for proj in report.project_suggestions:
            console.print(
                Panel(
                    f"[bold]{proj.name}[/bold]\n"
                    f"{proj.description}\n"
                    f"[dim]Skills: {', '.join(proj.skills_demonstrated)} | "
                    f"Effort: {proj.estimated_effort}[/dim]",
                    border_style="cyan",
                )
            )

    # Certification suggestions
    if report.certification_suggestions:
        cert_table = Table(title="Certifications Worth Pursuing")
        cert_table.add_column("Certification", style="cyan")
        cert_table.add_column("Issuer")
        cert_table.add_column("Relevance")
        for c in report.certification_suggestions:
            cert_table.add_row(c.name, c.issuer, c.relevance)
        console.print(cert_table)

    # Profile wording improvements
    if report.profile_wording:
        console.print("\n[bold]Profile Wording Improvements[/bold]")
        for pw in report.profile_wording:
            console.print(
                Panel(
                    f"[red]Current:[/red] {pw.current}\n"
                    f"[green]Suggested:[/green] {pw.suggested}\n"
                    f"[dim]Reason: {pw.reason}[/dim]",
                    border_style="yellow",
                )
            )

    console.print(
        "\n[dim]Run [bold]emplaiyed profile enhance[/bold] to improve "
        "your highlights, or [bold]emplaiyed profile build[/bold] "
        "to add missing information.[/dim]\n"
    )


@profile_app.command("enhance")
def profile_enhance() -> None:
    """Enrich duty-focused highlights with quantified achievements."""
    from emplaiyed.profile.enricher import enrich_profile

    try:
        asyncio.run(
            enrich_profile(
                prompt_fn=_rich_prompt,
                print_fn=_rich_print,
            )
        )
    except FileNotFoundError:
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Profile enhancement cancelled.[/yellow]")
        raise typer.Exit(code=0)
