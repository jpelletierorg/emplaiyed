"""Application lifecycle state machine.

Defines valid transitions between ApplicationStatus values and provides
functions to validate and perform transitions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from emplaiyed.core.database import get_application, save_application
from emplaiyed.core.models import Application, ApplicationStatus

# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: {ApplicationStatus.SCORED},
    ApplicationStatus.SCORED: {
        ApplicationStatus.OUTREACH_PENDING,
        ApplicationStatus.OUTREACH_SENT,  # backward compat (auto-send)
        ApplicationStatus.PASSED,
    },
    ApplicationStatus.OUTREACH_PENDING: {
        ApplicationStatus.OUTREACH_SENT,
        ApplicationStatus.SCORED,  # skip reverts
        ApplicationStatus.PASSED,
    },
    ApplicationStatus.OUTREACH_SENT: {
        ApplicationStatus.FOLLOW_UP_PENDING,
        ApplicationStatus.FOLLOW_UP_1,  # backward compat (auto-send)
        ApplicationStatus.RESPONSE_RECEIVED,
        ApplicationStatus.GHOSTED,
    },
    ApplicationStatus.FOLLOW_UP_PENDING: {
        ApplicationStatus.FOLLOW_UP_1,
        ApplicationStatus.FOLLOW_UP_2,
        ApplicationStatus.OUTREACH_SENT,  # skip reverts to previous
        ApplicationStatus.FOLLOW_UP_1,  # skip from FU2 pending
    },
    ApplicationStatus.FOLLOW_UP_1: {
        ApplicationStatus.FOLLOW_UP_PENDING,
        ApplicationStatus.FOLLOW_UP_2,  # backward compat (auto-send)
        ApplicationStatus.RESPONSE_RECEIVED,
        ApplicationStatus.GHOSTED,
    },
    ApplicationStatus.FOLLOW_UP_2: {
        ApplicationStatus.RESPONSE_RECEIVED,
        ApplicationStatus.GHOSTED,
    },
    ApplicationStatus.RESPONSE_RECEIVED: {
        ApplicationStatus.INTERVIEW_SCHEDULED,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.INTERVIEW_SCHEDULED: {
        ApplicationStatus.INTERVIEW_COMPLETED,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.INTERVIEW_COMPLETED: {
        ApplicationStatus.INTERVIEW_SCHEDULED,  # another round
        ApplicationStatus.OFFER_RECEIVED,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.OFFER_RECEIVED: {
        ApplicationStatus.NEGOTIATION_PENDING,
        ApplicationStatus.ACCEPTANCE_PENDING,
        ApplicationStatus.NEGOTIATING,  # backward compat
        ApplicationStatus.ACCEPTED,  # backward compat
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.NEGOTIATION_PENDING: {
        ApplicationStatus.NEGOTIATING,
        ApplicationStatus.OFFER_RECEIVED,  # skip reverts
    },
    ApplicationStatus.NEGOTIATING: {
        ApplicationStatus.OFFER_RECEIVED,  # counter-offer
        ApplicationStatus.ACCEPTANCE_PENDING,
        ApplicationStatus.ACCEPTED,  # backward compat
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.ACCEPTANCE_PENDING: {
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.OFFER_RECEIVED,  # skip reverts
        ApplicationStatus.NEGOTIATING,  # skip reverts
    },
    ApplicationStatus.ACCEPTED: set(),  # terminal
    ApplicationStatus.REJECTED: set(),  # terminal
    ApplicationStatus.GHOSTED: {
        ApplicationStatus.RESPONSE_RECEIVED,  # they might reply later
    },
    ApplicationStatus.PASSED: set(),  # terminal
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        current: ApplicationStatus,
        target: ApplicationStatus,
        application_id: str | None = None,
    ):
        self.current = current
        self.target = target
        self.application_id = application_id
        valid = VALID_TRANSITIONS.get(current, set())
        valid_str = ", ".join(sorted(s.value for s in valid)) if valid else "none (terminal state)"
        msg = (
            f"Cannot transition from {current.value} to {target.value}. "
            f"Valid transitions from {current.value}: {valid_str}."
        )
        if application_id:
            msg = f"Application {application_id}: {msg}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    """Return True if transitioning from *current* to *target* is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def transition(
    conn: sqlite3.Connection,
    application_id: str,
    target: ApplicationStatus,
) -> Application:
    """Validate and perform a status transition, updating the database.

    Returns the updated Application.
    Raises ``InvalidTransitionError`` if the transition is not valid.
    Raises ``ValueError`` if the application is not found.
    """
    app = get_application(conn, application_id)
    if app is None:
        raise ValueError(f"Application not found: {application_id}")

    if not can_transition(app.status, target):
        raise InvalidTransitionError(app.status, target, application_id)

    updated = app.model_copy(
        update={
            "status": target,
            "updated_at": datetime.now(),
        }
    )
    save_application(conn, updated)
    return updated
