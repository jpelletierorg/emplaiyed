"""Profile-to-prompt helpers — shared formatting used by LLM prompt builders."""

from __future__ import annotations

from emplaiyed.core.models import Profile


def format_skills(profile: Profile, limit: int = 10) -> str:
    """Format top skills as a comma-separated string."""
    if not profile.skills:
        return "Not specified"
    return ", ".join(profile.skills[:limit])


def format_recent_role(profile: Profile) -> str:
    """Format the most recent employment entry as 'Title at Company'."""
    if not profile.employment_history:
        return "Not specified"
    e = profile.employment_history[0]
    return f"{e.title} at {e.company}"


def format_salary_range(profile: Profile) -> tuple[int, int]:
    """Return (salary_min, salary_target) from aspirations, defaulting to 0."""
    if not profile.aspirations:
        return 0, 0
    return (
        profile.aspirations.salary_minimum or 0,
        profile.aspirations.salary_target or 0,
    )
