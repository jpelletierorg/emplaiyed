"""Contact extraction from job postings -- LLM and structured approaches."""

from __future__ import annotations

import logging
import re
import sqlite3

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.database import (
    get_contacts_for_opportunity,
    save_contact,
)
from emplaiyed.core.models import Contact, Opportunity
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM extraction output model
# ---------------------------------------------------------------------------


class ExtractedContact(BaseModel):
    """Structured contact info extracted from a job description."""

    name: str | None = Field(None, description="Full name of the contact person")
    email: str | None = Field(None, description="Email address")
    phone: str | None = Field(None, description="Phone number")
    title: str | None = Field(
        None,
        description="Role/title, e.g. 'Recruiter', 'Hiring Manager', 'HR Director'",
    )
    confidence: float = Field(
        0.0,
        description=(
            "0.0-1.0. 1.0 = explicit contact info stated clearly. "
            "0.5 = inferred from context. 0.0 = no contact info found."
        ),
    )
    found: bool = Field(False, description="True if any contact information was found")


_EXTRACTION_SYSTEM_PROMPT = """\
You extract contact information from job postings. Look for:
- Named people (recruiter name, hiring manager name)
- Email addresses (application emails, recruiter emails)
- Phone numbers
- Job titles of the contact person

IMPORTANT rules:
- Only extract REAL contact information that is explicitly stated or very clearly implied.
- Do NOT extract company phone numbers for switchboards or generic info lines.
- Do NOT extract generic emails like info@company.com or jobs@company.com unless \
there is no other option.
- If the posting says "apply online" with no person named, set found=false.
- Set confidence=1.0 for explicitly stated contacts ("Contact Jane Smith at jane@co.com").
- Set confidence=0.7 for strongly implied ("Send resume to talent@co.com").
- Set confidence=0.3 for generic channels ("Apply at jobs@co.com").
- Set confidence=0.0 and found=false if no useful contact info exists.
"""


async def extract_contact_llm(
    description: str,
    *,
    _model_override: Model | None = None,
) -> ExtractedContact:
    """Use the LLM to extract contact info from a job description."""
    from emplaiyed.llm.config import CONTACT_EXTRACTION_MODEL

    # Truncate to save tokens -- contact info is usually at the top or bottom
    text = description[:3000] if len(description) > 3000 else description

    prompt = (
        "Extract contact information from this job posting.\n\n"
        f"--- JOB POSTING ---\n{text}\n--- END ---"
    )

    return await complete_structured(
        prompt,
        ExtractedContact,
        system_prompt=_EXTRACTION_SYSTEM_PROMPT,
        model=CONTACT_EXTRACTION_MODEL,
        _model_override=_model_override,
    )


# ---------------------------------------------------------------------------
# Regex-based quick extraction (no LLM cost)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def extract_emails_regex(text: str) -> list[str]:
    """Quick regex extraction of email addresses from text.

    Filters out common generic/noreply patterns.
    """
    _GENERIC = {
        "noreply",
        "no-reply",
        "donotreply",
        "info@",
        "support@",
        "admin@",
        "postmaster@",
        "mailer-daemon",
    }
    emails = _EMAIL_RE.findall(text)
    return [e for e in emails if not any(g in e.lower() for g in _GENERIC)]


# ---------------------------------------------------------------------------
# Structured extraction from JSON-LD (Talent.com)
# ---------------------------------------------------------------------------


def extract_contact_jsonld(hiring_org: dict) -> ExtractedContact | None:
    """Extract contact info from a schema.org hiringOrganization dict.

    Looks for contactPoint, applicationContact, or similar fields.
    Returns None if nothing found.
    """
    contact_point = hiring_org.get("contactPoint")
    if not contact_point:
        # Also try applicationContact (some sites use this)
        contact_point = hiring_org.get("applicationContact")
    if not contact_point:
        return None

    if isinstance(contact_point, list):
        contact_point = contact_point[0] if contact_point else None
    if not isinstance(contact_point, dict):
        return None

    name = contact_point.get("name")
    email = contact_point.get("email")
    phone = contact_point.get("telephone")
    title = contact_point.get("contactType")

    if not any([name, email, phone]):
        return None

    return ExtractedContact(
        name=name,
        email=email,
        phone=phone,
        title=title,
        confidence=0.9,  # Structured data is high-confidence
        found=True,
    )


# ---------------------------------------------------------------------------
# Orchestrator -- extract + persist
# ---------------------------------------------------------------------------


async def extract_and_save_contacts(
    conn: sqlite3.Connection,
    opportunity: Opportunity,
    *,
    force: bool = False,
    _model_override: Model | None = None,
) -> list[Contact]:
    """Extract contacts from an opportunity and save to the database.

    If contacts already exist for this opportunity, returns them unless
    ``force=True``.

    Strategy:
    1. Check for existing contacts (skip if found and not forced).
    2. Try JSON-LD extraction if raw_data has hiringOrganization.
    3. Fall back to LLM extraction from description text.
    4. Fall back to regex extraction for emails (free).
    5. Save any found contacts to the database.
    """
    # Check existing
    if not force:
        existing = get_contacts_for_opportunity(conn, opportunity.id)
        if existing:
            return existing

    contacts: list[Contact] = []

    # --- Structured: JSON-LD ---
    if opportunity.raw_data and "hiring_org" in opportunity.raw_data:
        jsonld_contact = extract_contact_jsonld(opportunity.raw_data["hiring_org"])
        if jsonld_contact and jsonld_contact.found:
            contact = Contact(
                opportunity_id=opportunity.id,
                name=jsonld_contact.name,
                email=jsonld_contact.email,
                phone=jsonld_contact.phone,
                title=jsonld_contact.title,
                source="json_ld",
                confidence=jsonld_contact.confidence,
            )
            save_contact(conn, contact)
            contacts.append(contact)

    # --- LLM extraction from description ---
    if not contacts and opportunity.description:
        try:
            extracted = await extract_contact_llm(
                opportunity.description,
                _model_override=_model_override,
            )
            if extracted.found:
                contact = Contact(
                    opportunity_id=opportunity.id,
                    name=extracted.name,
                    email=extracted.email,
                    phone=extracted.phone,
                    title=extracted.title,
                    source="llm",
                    confidence=extracted.confidence,
                )
                save_contact(conn, contact)
                contacts.append(contact)
        except Exception:
            logger.warning(
                "LLM contact extraction failed for %s",
                opportunity.id,
                exc_info=True,
            )

    # --- Fallback: regex emails if LLM found nothing ---
    if not contacts and opportunity.description:
        emails = extract_emails_regex(opportunity.description)
        if emails:
            contact = Contact(
                opportunity_id=opportunity.id,
                email=emails[0],  # best guess: first non-generic email
                source="regex",
                confidence=0.3,
            )
            save_contact(conn, contact)
            contacts.append(contact)

    return contacts
