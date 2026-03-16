"""Stage grouping definitions for the pipeline console tabs."""

from __future__ import annotations

from emplaiyed.core.models import ApplicationStatus

# Each tab maps to a set of statuses that belong in that pipeline stage.
# Queue tab is handled separately (it uses work items, not status filtering).
STAGE_GROUPS: dict[str, list[ApplicationStatus]] = {
    "Applied": [
        ApplicationStatus.OUTREACH_SENT,
        ApplicationStatus.FOLLOW_UP_1,
        ApplicationStatus.FOLLOW_UP_2,
    ],
    "Active": [
        ApplicationStatus.RESPONSE_RECEIVED,
        ApplicationStatus.INTERVIEW_SCHEDULED,
        ApplicationStatus.INTERVIEW_COMPLETED,
    ],
    "Offers": [
        ApplicationStatus.OFFER_RECEIVED,
        ApplicationStatus.NEGOTIATION_PENDING,
        ApplicationStatus.NEGOTIATING,
        ApplicationStatus.ACCEPTANCE_PENDING,
    ],
    "Closed": [
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.GHOSTED,
        ApplicationStatus.PASSED,
    ],
}

# Ordered tab names (Queue and Funnel are special, not status-filtered)
STAGE_TAB_ORDER: list[str] = ["Queue", "Applied", "Active", "Offers", "Closed", "Funnel"]
