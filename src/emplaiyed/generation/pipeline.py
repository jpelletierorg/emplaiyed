"""Asset generation pipeline — orchestrates CV + letter generation and rendering."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model

from emplaiyed.core.database import get_opportunity, list_applications
from emplaiyed.core.models import (
    ApplicationStatus,
    Opportunity,
    Profile,
    WorkType,
)
from emplaiyed.core.profile_store import get_default_profile_path, load_profile
from emplaiyed.generation.config import EAGER_TOP_N
from emplaiyed.generation.cv_generator import GeneratedCV, generate_cv
from emplaiyed.generation.letter_generator import GeneratedLetter, generate_letter
from emplaiyed.rendering.markdown_renderer import write_cv_markdown, write_letter_markdown
from emplaiyed.rendering.pdf_renderer import render_cv_pdf, render_letter_pdf
from emplaiyed.work.queue import create_work_item

logger = logging.getLogger(__name__)


@dataclass
class AssetPaths:
    """Paths to the generated assets for one application."""
    cv_md: Path
    cv_pdf: Path
    letter_md: Path
    letter_pdf: Path


def get_asset_dir(app_id: str) -> Path:
    """Return the asset directory for an application, creating it if needed.

    Convention: ``<project_root>/data/assets/<app-id>/``
    """
    root = _find_project_root()
    asset_dir = root / "data" / "assets" / app_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    return asset_dir


def _find_project_root() -> Path:
    from emplaiyed.core.paths import find_project_root

    return find_project_root()


def has_assets(app_id: str) -> bool:
    """Check if assets already exist for an application."""
    d = get_asset_dir(app_id)
    return (d / "cv.pdf").exists() and (d / "letter.pdf").exists()


async def generate_assets(
    profile: Profile,
    opportunity: Opportunity,
    app_id: str,
    *,
    _model_override: Model | None = None,
    asset_dir: Path | None = None,
) -> AssetPaths:
    """Generate CV + letter, render to markdown + PDF, return file paths.

    Args:
        profile: Candidate profile.
        opportunity: Target job opportunity.
        app_id: Application ID (used for directory naming).
        _model_override: Inject TestModel for tests.
        asset_dir: Override asset directory (for tests). Defaults to
            ``data/assets/<app_id>/``.
    """
    out = asset_dir or get_asset_dir(app_id)

    # Generate CV and letter concurrently
    cv, letter_obj = await asyncio.gather(
        generate_cv(profile, opportunity, _model_override=_model_override),
        generate_letter(profile, opportunity, _model_override=_model_override),
    )

    # Render to all formats
    paths = AssetPaths(
        cv_md=out / "cv.md",
        cv_pdf=out / "cv.pdf",
        letter_md=out / "letter.md",
        letter_pdf=out / "letter.pdf",
    )
    write_cv_markdown(cv, paths.cv_md)
    render_cv_pdf(cv, paths.cv_pdf)
    write_letter_markdown(letter_obj, paths.letter_md)
    render_letter_pdf(letter_obj, paths.letter_pdf)

    logger.debug("Assets generated for %s in %s", app_id, out)
    return paths


def _build_work_instructions(
    opportunity: Opportunity,
    paths: AssetPaths,
) -> str:
    """Build the work item instructions with asset references."""
    lines = []

    if opportunity.source_url:
        lines.append(f"**Apply here:** {opportunity.source_url}")
        lines.append("")

    lines.extend([
        "### Assets",
        f"- CV:     {paths.cv_pdf}",
        f"- Letter: {paths.letter_pdf}",
    ])

    return "\n".join(lines)


async def generate_assets_and_enqueue(
    conn: sqlite3.Connection,
    profile: Profile,
    opportunity: Opportunity,
    app_id: str,
    *,
    _model_override: Model | None = None,
    asset_dir: Path | None = None,
) -> AssetPaths:
    """Generate assets and create a work item for an application.

    This is the main entry point for the eager generation path.
    """
    paths = await generate_assets(
        profile, opportunity, app_id,
        _model_override=_model_override,
        asset_dir=asset_dir,
    )

    instructions = _build_work_instructions(opportunity, paths)

    create_work_item(
        conn,
        application_id=app_id,
        work_type=WorkType.OUTREACH,
        title=f"Apply to {opportunity.company} — {opportunity.title}",
        instructions=instructions,
        target_status=ApplicationStatus.OUTREACH_SENT,
        previous_status=ApplicationStatus.SCORED,
        pending_status=ApplicationStatus.OUTREACH_PENDING,
    )

    return paths


async def generate_assets_batch(
    conn: sqlite3.Connection,
    profile: Profile,
    scored_apps: list[tuple[str, Opportunity]],
    *,
    top_n: int | None = None,
    _model_override: Model | None = None,
) -> list[AssetPaths]:
    """Generate assets for the top N scored applications concurrently.

    Args:
        conn: Database connection.
        profile: Candidate profile.
        scored_apps: List of (app_id, opportunity) tuples, sorted by score descending.
        top_n: Number of top apps to process. Defaults to EAGER_TOP_N.
        _model_override: Inject TestModel for tests.

    Returns:
        List of AssetPaths for successfully generated assets.
    """
    n = top_n if top_n is not None else EAGER_TOP_N
    targets = scored_apps[:n]

    if not targets:
        return []

    async def _generate_one(app_id: str, opportunity: Opportunity) -> AssetPaths | None:
        for attempt in range(3):
            try:
                return await generate_assets_and_enqueue(
                    conn, profile, opportunity, app_id,
                    _model_override=_model_override,
                )
            except Exception as exc:
                if attempt < 2 and "onnect" in str(exc):
                    logger.debug("Retry %d for %s: %s", attempt + 1, opportunity.company, exc)
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                logger.warning(
                    "Failed to generate assets for %s (%s): %s",
                    opportunity.company, app_id, exc,
                )
                return None
        return None

    outcomes = await asyncio.gather(
        *(_generate_one(app_id, opp) for app_id, opp in targets)
    )
    return [p for p in outcomes if p is not None]
