"""Map candidate profile data to application form fields.

Provides a field-value mapping from Profile data to common form field
names/labels used by ATS platforms and generic job application forms.
Only fills required fields; optional fields are skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from emplaiyed.core.models import Profile

logger = logging.getLogger(__name__)


@dataclass
class FieldMapping:
    """A single form field and the value to fill it with."""

    selector: str
    value: str
    field_type: str = "text"  # "text", "file", "select", "textarea"


@dataclass
class FormPlan:
    """A complete plan for filling out an application form."""

    text_fields: list[FieldMapping] = field(default_factory=list)
    file_uploads: list[FieldMapping] = field(default_factory=list)
    unmapped_required: list[str] = field(default_factory=list)


# Common field name/label patterns mapped to profile attributes
_FIELD_MAP: list[tuple[list[str], str]] = [
    # Name fields
    (
        ["first_name", "first name", "firstname", "prenom", "given_name", "given name"],
        "first_name",
    ),
    (
        [
            "last_name",
            "last name",
            "lastname",
            "nom",
            "family_name",
            "family name",
            "surname",
        ],
        "last_name",
    ),
    (
        ["full_name", "full name", "name", "nom complet", "your name"],
        "full_name",
    ),
    # Contact
    (
        ["email", "e-mail", "courriel", "email_address", "email address"],
        "email",
    ),
    (
        ["phone", "telephone", "phone_number", "phone number", "tel"],
        "phone",
    ),
    # Location
    (
        ["city", "ville"],
        "city",
    ),
    (
        ["location", "emplacement", "address", "adresse"],
        "location",
    ),
    # Links
    (
        ["linkedin", "linkedin_url", "linkedin url", "linkedin profile"],
        "linkedin",
    ),
    (
        ["github", "github_url", "github url", "portfolio", "website"],
        "github",
    ),
]


def _extract_first_last(profile: Profile) -> tuple[str, str]:
    """Split profile name into first and last name."""
    parts = profile.name.strip().split(maxsplit=1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def _get_profile_value(profile: Profile, key: str) -> str | None:
    """Get a value from the profile by logical key."""
    first, last = _extract_first_last(profile)
    values = {
        "first_name": first,
        "last_name": last,
        "full_name": profile.name,
        "email": profile.email,
        "phone": profile.phone,
        "city": profile.address.city if profile.address else None,
        "location": _format_location(profile),
        "linkedin": profile.linkedin,
        "github": profile.github,
    }
    return values.get(key)


def _format_location(profile: Profile) -> str | None:
    """Format address as a location string."""
    if not profile.address:
        return None
    parts = [
        profile.address.city,
        profile.address.province_state,
        profile.address.country,
    ]
    return ", ".join(p for p in parts if p)


def build_form_plan(
    profile: Profile,
    fields: list[dict],
    *,
    resume_path: Path | None = None,
    letter_path: Path | None = None,
) -> FormPlan:
    """Build a plan for filling a form given discovered fields.

    Args:
        profile: Candidate profile.
        fields: List of field descriptors, each with keys:
            - selector: CSS selector
            - name: field name attribute
            - label: visible label text
            - required: whether the field is required
            - type: input type (text, file, email, tel, etc.)
        resume_path: Path to resume/CV file for upload.
        letter_path: Path to cover letter file for upload.

    Returns:
        FormPlan with text fields to fill, files to upload, and
        any required fields that could not be mapped.
    """
    plan = FormPlan()

    for f in fields:
        selector = f["selector"]
        name = (f.get("name") or "").lower()
        label = (f.get("label") or "").lower()
        required = f.get("required", False)
        field_type = (f.get("type") or "text").lower()

        # File upload fields
        if field_type == "file":
            if _matches_any(name, label, ["resume", "cv", "curriculum"]):
                if resume_path and resume_path.exists():
                    plan.file_uploads.append(
                        FieldMapping(selector, str(resume_path), "file")
                    )
                elif required:
                    plan.unmapped_required.append(f"File upload: {label or name}")
            elif _matches_any(name, label, ["cover", "letter", "lettre", "motivation"]):
                if letter_path and letter_path.exists():
                    plan.file_uploads.append(
                        FieldMapping(selector, str(letter_path), "file")
                    )
                elif required:
                    plan.unmapped_required.append(f"File upload: {label or name}")
            elif required:
                plan.unmapped_required.append(f"File upload: {label or name}")
            continue

        # Skip optional fields
        if not required:
            continue

        # Try to map text/select fields
        matched = False
        for patterns, profile_key in _FIELD_MAP:
            if _matches_any(name, label, patterns):
                value = _get_profile_value(profile, profile_key)
                if value:
                    plan.text_fields.append(FieldMapping(selector, value, field_type))
                    matched = True
                else:
                    plan.unmapped_required.append(f"{label or name} (no profile data)")
                    matched = True
                break

        if not matched:
            plan.unmapped_required.append(label or name)

    return plan


def _matches_any(name: str, label: str, patterns: list[str]) -> bool:
    """Check if a field name or label matches any of the given patterns."""
    combined = f"{name} {label}"
    return any(p in combined for p in patterns)
