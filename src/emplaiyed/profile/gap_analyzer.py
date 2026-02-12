"""Gap Analyzer — identifies missing/empty fields in a Profile.

Compares a (possibly partial) Profile against the ideal "job-search-ready"
state and returns categorised gaps so the conversational builder knows what
questions to ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from emplaiyed.core.models import Aspirations, Profile


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class GapPriority(str, Enum):
    """How important a gap is for the job search workflow."""

    REQUIRED = "required"
    NICE_TO_HAVE = "nice_to_have"


@dataclass
class Gap:
    """A single missing or empty field."""

    field_name: str
    description: str
    priority: GapPriority


@dataclass
class GapReport:
    """The full gap analysis result."""

    gaps: list[Gap] = field(default_factory=list)

    @property
    def required_gaps(self) -> list[Gap]:
        return [g for g in self.gaps if g.priority == GapPriority.REQUIRED]

    @property
    def nice_to_have_gaps(self) -> list[Gap]:
        return [g for g in self.gaps if g.priority == GapPriority.NICE_TO_HAVE]

    @property
    def is_complete(self) -> bool:
        """True when there are no required gaps."""
        return len(self.required_gaps) == 0

    @property
    def is_fully_complete(self) -> bool:
        """True when there are no gaps at all."""
        return len(self.gaps) == 0


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_gaps(profile: Profile) -> GapReport:
    """Examine *profile* and return a :class:`GapReport` of missing fields.

    Required fields (for job search):
    - aspirations.target_roles
    - aspirations.salary_minimum
    - aspirations.salary_target
    - aspirations.urgency
    - aspirations.geographic_preferences
    - aspirations.work_arrangement
    - skills

    Nice-to-have fields:
    - languages
    - certifications
    """
    gaps: list[Gap] = []

    # ---- Required: skills ----
    if not profile.skills:
        gaps.append(
            Gap(
                field_name="skills",
                description="What are your key technical and professional skills?",
                priority=GapPriority.REQUIRED,
            )
        )

    # ---- Required: aspirations ----
    asp = profile.aspirations
    if asp is None:
        # All aspiration sub-fields are missing
        gaps.extend(_all_aspiration_gaps())
    else:
        gaps.extend(_aspiration_field_gaps(asp))

    # ---- Nice to have ----
    if not profile.languages:
        gaps.append(
            Gap(
                field_name="languages",
                description="What languages do you speak and at what proficiency?",
                priority=GapPriority.NICE_TO_HAVE,
            )
        )

    if not profile.certifications:
        gaps.append(
            Gap(
                field_name="certifications",
                description="Do you have any professional certifications?",
                priority=GapPriority.NICE_TO_HAVE,
            )
        )

    return GapReport(gaps=gaps)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_aspiration_gaps() -> list[Gap]:
    """Return gaps for every aspiration sub-field."""
    return [
        Gap(
            field_name="aspirations.target_roles",
            description="What kind of roles are you looking for?",
            priority=GapPriority.REQUIRED,
        ),
        Gap(
            field_name="aspirations.salary_minimum",
            description="What is your minimum acceptable salary?",
            priority=GapPriority.REQUIRED,
        ),
        Gap(
            field_name="aspirations.salary_target",
            description="What is your target salary?",
            priority=GapPriority.REQUIRED,
        ),
        Gap(
            field_name="aspirations.urgency",
            description="How urgently are you looking for a new role?",
            priority=GapPriority.REQUIRED,
        ),
        Gap(
            field_name="aspirations.geographic_preferences",
            description="Where are you willing to work? (cities, remote, etc.)",
            priority=GapPriority.REQUIRED,
        ),
        Gap(
            field_name="aspirations.work_arrangement",
            description="What work arrangement do you prefer? (remote, hybrid, on-site)",
            priority=GapPriority.REQUIRED,
        ),
    ]


def _aspiration_field_gaps(asp: Aspirations) -> list[Gap]:
    """Return gaps for individual aspiration fields that are empty/None."""
    gaps: list[Gap] = []

    if not asp.target_roles:
        gaps.append(
            Gap(
                field_name="aspirations.target_roles",
                description="What kind of roles are you looking for?",
                priority=GapPriority.REQUIRED,
            )
        )

    if asp.salary_minimum is None:
        gaps.append(
            Gap(
                field_name="aspirations.salary_minimum",
                description="What is your minimum acceptable salary?",
                priority=GapPriority.REQUIRED,
            )
        )

    if asp.salary_target is None:
        gaps.append(
            Gap(
                field_name="aspirations.salary_target",
                description="What is your target salary?",
                priority=GapPriority.REQUIRED,
            )
        )

    if asp.urgency is None:
        gaps.append(
            Gap(
                field_name="aspirations.urgency",
                description="How urgently are you looking for a new role?",
                priority=GapPriority.REQUIRED,
            )
        )

    if not asp.geographic_preferences:
        gaps.append(
            Gap(
                field_name="aspirations.geographic_preferences",
                description="Where are you willing to work? (cities, remote, etc.)",
                priority=GapPriority.REQUIRED,
            )
        )

    if not asp.work_arrangement:
        gaps.append(
            Gap(
                field_name="aspirations.work_arrangement",
                description="What work arrangement do you prefer? (remote, hybrid, on-site)",
                priority=GapPriority.REQUIRED,
            )
        )

    return gaps
