"""Work queue — human-in-the-loop task management.

Creates self-contained work items that a human picks up, executes,
and marks done. State only advances when the human confirms.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from emplaiyed.core.database import (
    get_application,
    get_work_item,
    save_interaction,
    save_work_item,
)
from emplaiyed.core.models import (
    ApplicationStatus,
    Interaction,
    InteractionType,
    WorkItem,
    WorkStatus,
    WorkType,
)
from emplaiyed.tracker.state_machine import transition

logger = logging.getLogger(__name__)


def create_work_item(
    conn: sqlite3.Connection,
    *,
    application_id: str,
    work_type: WorkType,
    title: str,
    instructions: str,
    draft_content: str | None = None,
    target_status: ApplicationStatus,
    previous_status: ApplicationStatus,
    pending_status: ApplicationStatus,
) -> WorkItem:
    """Create a work item and transition the application to its PENDING state.

    Args:
        conn: Database connection.
        application_id: The application this work item belongs to.
        work_type: Type of work (OUTREACH, FOLLOW_UP, etc.).
        title: Human-readable title for the work item.
        instructions: Full markdown instructions for the human.
        draft_content: Optional raw email draft for copy-paste.
        target_status: Status to transition to when "done".
        previous_status: Status to revert to when "skip".
        pending_status: The PENDING status to transition to now.
    """
    # Transition to the PENDING state
    transition(conn, application_id, pending_status)

    item = WorkItem(
        application_id=application_id,
        work_type=work_type,
        title=title,
        instructions=instructions,
        draft_content=draft_content,
        target_status=target_status.value,
        previous_status=previous_status.value,
        created_at=datetime.now(),
    )
    save_work_item(conn, item)
    logger.debug("Work item created: %s (%s)", item.id, title)
    return item


def complete_work_item(
    conn: sqlite3.Connection,
    work_item_id: str,
) -> WorkItem:
    """Mark a work item as done, record the interaction, and advance the state.

    Raises ValueError if the work item is not found or not PENDING.
    """
    item = get_work_item(conn, work_item_id)
    if item is None:
        raise ValueError(f"Work item not found: {work_item_id}")
    if item.status != WorkStatus.PENDING:
        raise ValueError(f"Work item {work_item_id} is already {item.status.value}")

    target = ApplicationStatus(item.target_status)

    # Record the interaction
    interaction = Interaction(
        application_id=item.application_id,
        type=_interaction_type_for(item.work_type),
        direction="outbound",
        channel="email",
        content=item.draft_content,
        created_at=datetime.now(),
    )
    save_interaction(conn, interaction)

    # Transition the application
    transition(conn, item.application_id, target)

    # Mark work item complete
    updated = item.model_copy(
        update={
            "status": WorkStatus.COMPLETED,
            "completed_at": datetime.now(),
        }
    )
    save_work_item(conn, updated)
    logger.debug("Work item completed: %s → %s", work_item_id, target.value)
    return updated


def skip_work_item(
    conn: sqlite3.Connection,
    work_item_id: str,
) -> WorkItem:
    """Skip a work item and revert the application to its previous state.

    Raises ValueError if the work item is not found or not PENDING.
    """
    item = get_work_item(conn, work_item_id)
    if item is None:
        raise ValueError(f"Work item not found: {work_item_id}")
    if item.status != WorkStatus.PENDING:
        raise ValueError(f"Work item {work_item_id} is already {item.status.value}")

    previous = ApplicationStatus(item.previous_status)

    # Revert the application state
    transition(conn, item.application_id, previous)

    # Mark work item skipped
    updated = item.model_copy(
        update={
            "status": WorkStatus.SKIPPED,
            "completed_at": datetime.now(),
        }
    )
    save_work_item(conn, updated)
    logger.debug("Work item skipped: %s → %s", work_item_id, previous.value)
    return updated


def _interaction_type_for(work_type: WorkType) -> InteractionType:
    """Map work type to interaction type."""
    if work_type == WorkType.FOLLOW_UP:
        return InteractionType.FOLLOW_UP
    return InteractionType.EMAIL_SENT
