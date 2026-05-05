"""Apply orchestrator — runs the full autonomous application flow.

Coordinates asset generation, then delegates to the pydantic_ai apply agent
which manages Browser Use v3 sessions and email verification through
proper tool calling.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from emplaiyed.apply.apply_agent import run_apply_agent
from emplaiyed.apply.config import get_browser_use_config
from emplaiyed.apply.logging_setup import configure_apply_logging
from emplaiyed.core.database import (
    get_application,
    get_opportunity,
    save_apply_run,
    save_interaction,
)
from emplaiyed.core.models import (
    ApplyRun,
    ApplyRunStatus,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Profile,
)
from emplaiyed.generation.pipeline import generate_assets, get_asset_dir, has_assets
from emplaiyed.tracker.state_machine import transition

logger = logging.getLogger(__name__)


def _update_run(
    conn: sqlite3.Connection,
    run: ApplyRun,
    *,
    status: ApplyRunStatus | None = None,
    last_step: str | None = None,
    current_url: str | None = None,
    error_message: str | None = None,
) -> ApplyRun:
    """Update an ApplyRun with new state and persist it."""
    updates: dict = {"updated_at": datetime.now()}
    if status is not None:
        updates["status"] = status
    if last_step is not None:
        updates["last_step"] = last_step
    if current_url is not None:
        updates["current_url"] = current_url
    if error_message is not None:
        updates["error_message"] = error_message
    if status in (
        ApplyRunStatus.SUCCEEDED,
        ApplyRunStatus.FAILED,
        ApplyRunStatus.BLOCKED,
        ApplyRunStatus.CANCELLED,
    ):
        updates["completed_at"] = datetime.now()

    run = run.model_copy(update=updates)
    save_apply_run(conn, run)
    return run


def _generate_account_email(short_id: str, base_email: str) -> str:
    """Generate a unique portal email like moi+abc123@jpelletier.org."""
    local, domain = base_email.split("@", 1)
    return f"{local}+{short_id}@{domain}"


async def run_apply(
    conn: sqlite3.Connection,
    run: ApplyRun,
    profile: Profile,
) -> ApplyRun:
    """Execute a full apply run via the pydantic_ai apply agent.

    This is the main entry point called by the Textual @work worker.
    """
    configure_apply_logging()

    app = get_application(conn, run.application_id)
    if app is None:
        return _update_run(
            conn,
            run,
            status=ApplyRunStatus.FAILED,
            error_message="Application not found",
        )

    opp = get_opportunity(conn, app.opportunity_id)
    if opp is None:
        return _update_run(
            conn,
            run,
            status=ApplyRunStatus.FAILED,
            error_message="Opportunity not found",
        )

    if not opp.source_url:
        return _update_run(
            conn,
            run,
            status=ApplyRunStatus.FAILED,
            error_message="No source URL on opportunity",
        )

    # Load Browser Use config
    try:
        config = get_browser_use_config()
    except RuntimeError as exc:
        return _update_run(
            conn,
            run,
            status=ApplyRunStatus.FAILED,
            error_message=str(exc),
        )

    asset_dir = get_asset_dir(app.id)
    run = run.model_copy(update={"artifact_dir": str(asset_dir)})

    # Step 1: Generate assets if needed
    if not has_assets(app.id):
        run = _update_run(
            conn,
            run,
            status=ApplyRunStatus.GENERATING_ASSETS,
            last_step="Generating CV and cover letter",
        )
        try:
            await generate_assets(profile, opp, app.id)
        except Exception as exc:
            logger.exception("Asset generation failed for %s", app.id)
            return _update_run(
                conn,
                run,
                status=ApplyRunStatus.FAILED,
                error_message=f"Asset generation failed: {exc}",
            )

    resume_path = asset_dir / "cv.pdf"
    letter_path = asset_dir / "letter.pdf"

    # Step 2: Generate unique account email
    account_email = _generate_account_email(opp.short_id, profile.email)

    # Step 3: Run the apply agent
    run = _update_run(
        conn,
        run,
        status=ApplyRunStatus.NAVIGATING,
        last_step=f"Apply agent: starting for {opp.company}",
        current_url=opp.source_url,
    )

    try:
        logger.info(
            "Starting apply agent for %s (%s) at %s",
            opp.company,
            opp.title,
            opp.source_url,
        )

        result = await run_apply_agent(
            config,
            profile,
            opp,
            resume_path=resume_path,
            letter_path=letter_path,
            account_email=account_email,
        )

        logger.info(
            "Apply agent finished: submitted=%s",
            result.submitted,
        )

        if result.submitted:
            run = _update_run(
                conn,
                run,
                status=ApplyRunStatus.SUCCEEDED,
                last_step="Application submitted successfully",
                current_url=result.final_url,
            )

            save_interaction(
                conn,
                Interaction(
                    application_id=app.id,
                    type=InteractionType.FORM_SUBMITTED,
                    direction="outbound",
                    channel="browser",
                    content=result.confirmation_text or "Submitted via apply agent",
                    created_at=datetime.now(),
                ),
            )

            try:
                transition(conn, app.id, ApplicationStatus.OUTREACH_SENT)
            except Exception:
                logger.warning(
                    "Could not transition %s to OUTREACH_SENT",
                    app.id,
                    exc_info=True,
                )

            return run
        else:
            return _update_run(
                conn,
                run,
                status=ApplyRunStatus.BLOCKED,
                error_message=result.error_reason or "Submission not confirmed",
                last_step=f"Blocked: {result.error_reason or 'no confirmation'}",
                current_url=result.final_url,
            )

    except Exception as exc:
        logger.exception("Apply run failed for %s", run.id)
        return _update_run(
            conn,
            run,
            status=ApplyRunStatus.FAILED,
            error_message=str(exc),
            last_step="Apply agent error",
        )
