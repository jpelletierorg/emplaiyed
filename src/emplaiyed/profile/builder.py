"""Conversational Profile Builder — the main orchestrator for
``emplaiyed profile build``.

Responsibilities:
- Greet the user and ask if they have a CV
- Parse the CV if provided (via cv_parser)
- Present extraction results and allow corrections
- Identify gaps (via gap_analyzer) and ask targeted questions
- Save the completed profile
- Support incremental updates when a profile already exists

The builder is designed to be driven by a pair of callables for I/O so that
it can be tested without a real terminal.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from pydantic_ai.models import Model

logger = logging.getLogger(__name__)

from emplaiyed.core.models import Aspirations, Profile
from emplaiyed.core.profile_store import (
    get_default_profile_path,
    load_profile,
    save_profile,
)
from emplaiyed.llm.engine import complete, complete_structured
from emplaiyed.profile.cv_parser import parse_cv
from emplaiyed.profile.gap_analyzer import (
    GapPriority,
    GapReport,
    analyze_gaps,
)


# ---------------------------------------------------------------------------
# I/O protocol — allows injection of fake I/O for tests
# ---------------------------------------------------------------------------

class PromptFunc(Protocol):
    """Callable that displays a message and returns user input."""

    def __call__(self, message: str) -> str: ...


class PrintFunc(Protocol):
    """Callable that displays a message to the user."""

    def __call__(self, message: str) -> None: ...


# ---------------------------------------------------------------------------
# Profile merging
# ---------------------------------------------------------------------------

def _merge_profiles(base: Profile, update: Profile) -> Profile:
    """Merge *update* into *base*, preferring non-empty values from *update*.

    For scalar fields, *update* wins if it is not None/empty.
    For list fields, *update* wins if it is non-empty.
    """
    merged_data = base.model_dump()

    for field_name, field_info in Profile.model_fields.items():
        update_val = getattr(update, field_name)
        base_val = getattr(base, field_name)

        if isinstance(update_val, list):
            if update_val:  # non-empty list wins
                merged_data[field_name] = update.model_dump()[field_name]
        elif update_val is not None:
            # For sub-models, merge recursively if base also has a value
            if hasattr(update_val, "model_dump") and base_val is not None:
                base_dict = base_val.model_dump()
                update_dict = update_val.model_dump()
                for k, v in update_dict.items():
                    if v is not None:
                        base_dict[k] = v
                merged_data[field_name] = base_dict
            else:
                merged_data[field_name] = update.model_dump()[field_name]

    return Profile.model_validate(merged_data)


# ---------------------------------------------------------------------------
# Question grouping
# ---------------------------------------------------------------------------

_QUESTION_GROUPS: list[tuple[str, list[str]]] = [
    (
        "roles_and_arrangement",
        [
            "aspirations.target_roles",
            "aspirations.work_arrangement",
            "aspirations.geographic_preferences",
        ],
    ),
    (
        "salary",
        [
            "aspirations.salary_minimum",
            "aspirations.salary_target",
        ],
    ),
    (
        "urgency",
        [
            "aspirations.urgency",
        ],
    ),
    (
        "skills",
        [
            "skills",
        ],
    ),
    (
        "languages",
        [
            "languages",
        ],
    ),
    (
        "certifications",
        [
            "certifications",
        ],
    ),
]


def _group_questions(gap_report: GapReport) -> list[tuple[str, list[str]]]:
    """Given a gap report, return question groups that contain at least one gap.

    Each entry is (group_name, [field_names_that_are_gaps]).
    """
    gap_field_names = {g.field_name for g in gap_report.gaps}
    result: list[tuple[str, list[str]]] = []
    for group_name, fields in _QUESTION_GROUPS:
        matching = [f for f in fields if f in gap_field_names]
        if matching:
            result.append((group_name, matching))
    return result


# ---------------------------------------------------------------------------
# Prompt templates for gap-filling
# ---------------------------------------------------------------------------

_GROUP_PROMPTS: dict[str, str] = {
    "roles_and_arrangement": (
        "What kind of roles are you looking for, what's your preferred work "
        "arrangement (remote/hybrid/on-site), and where are you willing to work?"
    ),
    "salary": (
        "What's your salary expectation? (minimum and target)"
    ),
    "urgency": (
        "How urgent is your job search?"
    ),
    "skills": (
        "What are your key technical and professional skills?"
    ),
    "languages": (
        "What languages do you speak and at what proficiency level?"
    ),
    "certifications": (
        "Do you have any professional certifications?"
    ),
}


# ---------------------------------------------------------------------------
# LLM-assisted answer parsing
# ---------------------------------------------------------------------------

_CORRECTION_PROMPT = """\
The user was shown their CV extraction and wants corrections.
Current profile data (JSON):
{profile_json}

User's correction request:
"{user_input}"

Return the updated Profile with the corrections applied. Only change fields
the user explicitly mentioned. Keep everything else the same.
"""

_ANSWER_PARSE_PROMPT = """\
The user was asked about the following profile fields: {fields}
Their answer: "{user_input}"

Current profile data (JSON):
{profile_json}

Parse the user's answer and return the complete updated Profile.
Only update the fields related to the question. Keep all other fields unchanged.
"""


async def _apply_corrections(
    profile: Profile,
    user_input: str,
    *,
    _model_override: Model | None = None,
) -> Profile:
    """Use the LLM to apply free-text corrections to the profile."""
    prompt = _CORRECTION_PROMPT.format(
        profile_json=profile.model_dump_json(indent=2),
        user_input=user_input,
    )
    return await complete_structured(
        prompt,
        output_type=Profile,
        _model_override=_model_override,
    )


async def _parse_answer(
    profile: Profile,
    fields: list[str],
    user_input: str,
    *,
    _model_override: Model | None = None,
) -> Profile:
    """Use the LLM to parse a free-text answer into profile field updates."""
    prompt = _ANSWER_PARSE_PROMPT.format(
        fields=", ".join(fields),
        user_input=user_input,
        profile_json=profile.model_dump_json(indent=2),
    )
    return await complete_structured(
        prompt,
        output_type=Profile,
        _model_override=_model_override,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_profile_summary(profile: Profile) -> str:
    """Build a human-readable summary of what was extracted."""
    lines: list[str] = []
    lines.append(f"  Name:       {profile.name}")
    lines.append(f"  Email:      {profile.email}")
    if profile.phone:
        lines.append(f"  Phone:      {profile.phone}")
    if profile.address:
        addr_parts = [
            p
            for p in [
                profile.address.street,
                profile.address.city,
                profile.address.province_state,
                profile.address.country,
            ]
            if p
        ]
        if addr_parts:
            lines.append(f"  Location:   {', '.join(addr_parts)}")
    if profile.skills:
        lines.append(f"  Skills:     {', '.join(profile.skills)}")
    if profile.education:
        for edu in profile.education:
            lines.append(f"  Education:  {edu.degree} in {edu.field} @ {edu.institution}")
    if profile.employment_history:
        for emp in profile.employment_history:
            end = str(emp.end_date) if emp.end_date else "Present"
            start = str(emp.start_date) if emp.start_date else "?"
            lines.append(f"  Employment: {emp.title} at {emp.company} ({start} - {end})")
    if profile.languages:
        lang_str = ", ".join(
            f"{l.language} ({l.proficiency})" for l in profile.languages
        )
        lines.append(f"  Languages:  {lang_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

async def build_profile(
    *,
    prompt_fn: PromptFunc,
    print_fn: PrintFunc,
    profile_path: Path | None = None,
    _model_override: Model | None = None,
) -> Profile:
    """Run the interactive profile builder.

    Parameters
    ----------
    prompt_fn:
        Callable that shows a message and returns user input.
    print_fn:
        Callable that displays text to the user.
    profile_path:
        Where to save the profile. Defaults to ``get_default_profile_path()``.
    _model_override:
        Inject a Pydantic-AI Model for testing.
    """
    path = profile_path or get_default_profile_path()
    logger.debug("Profile build starting, path=%s", path)

    # -- Check for existing profile --
    existing_profile: Profile | None = None
    if path.exists():
        try:
            existing_profile = load_profile(path)
        except Exception:
            existing_profile = None

    # -- Greeting --
    print_fn(
        "\nWelcome to emplaiyed. I'm going to help you build your job seeker profile.\n"
        "This profile drives everything — tailored CVs, outreach messaging, scoring.\n"
    )

    if existing_profile:
        print_fn("I found an existing profile:\n")
        print_fn(format_profile_summary(existing_profile))
        print_fn("")

    # -- CV parsing --
    profile: Profile | None = existing_profile

    cv_answer = prompt_fn(
        "Do you have an existing CV/resume I can start from? "
        "(Enter file path, or 'no' to skip)"
    )

    if cv_answer.strip().lower() not in ("no", "n", "none", "skip", ""):
        cv_path = Path(cv_answer.strip())
        print_fn("\nParsing your CV...\n")
        try:
            cv_profile = await parse_cv(cv_path, _model_override=_model_override)
            if profile:
                profile = _merge_profiles(profile, cv_profile)
            else:
                profile = cv_profile

            print_fn("Here's what I extracted:\n")
            print_fn(format_profile_summary(profile))
            print_fn("")

            # -- Correction loop --
            correction = prompt_fn(
                "Anything wrong or outdated here? (Enter corrections, or 'no' to continue)"
            )
            if correction.strip().lower() not in ("no", "n", "none", "looks good", ""):
                profile = await _apply_corrections(
                    profile, correction, _model_override=_model_override
                )
                print_fn("\nGot it — profile updated.\n")

        except (FileNotFoundError, ValueError) as exc:
            print_fn(f"\nCouldn't parse CV: {exc}")
            print_fn("Let's build your profile from scratch instead.\n")

    # -- Initialize a blank profile if we still don't have one --
    if profile is None:
        name = prompt_fn("What is your full name?")
        email = prompt_fn("What is your email address?")
        profile = Profile(name=name.strip(), email=email.strip())

    # -- Gap analysis and filling --
    gap_report = analyze_gaps(profile)
    logger.debug("Gap analysis: %d gaps found", len(gap_report.gaps))

    if gap_report.gaps:
        required_count = len(gap_report.required_gaps)
        nice_count = len(gap_report.nice_to_have_gaps)

        if required_count > 0:
            print_fn(
                f"Now I need a few things your CV doesn't cover "
                f"({required_count} required, {nice_count} optional):\n"
            )
        elif nice_count > 0:
            print_fn(
                f"Your profile covers the essentials! "
                f"I have {nice_count} optional questions to make it even better:\n"
            )

        groups = _group_questions(gap_report)

        for group_name, fields in groups:
            question = _GROUP_PROMPTS.get(group_name, f"Tell me about: {', '.join(fields)}")
            answer = prompt_fn(question)

            if answer.strip().lower() in ("skip", "none", ""):
                continue

            profile = await _parse_answer(
                profile, fields, answer, _model_override=_model_override
            )

    # -- Save --
    save_profile(profile, path)
    print_fn(f"\nProfile saved to {path}")
    print_fn("Run `emplaiyed profile show` to review it anytime.\n")

    return profile
