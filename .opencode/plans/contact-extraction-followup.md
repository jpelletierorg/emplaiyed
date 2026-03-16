# Contact Extraction & Follow-Up Content Generation Plan

## Overview

Add the ability to extract contact information (recruiter name, email, phone) from job postings using both structured scraper-time extraction and LLM-based extraction from free text. Then generate personalized follow-up content targeted at the extracted contact. Includes a minimal web UI to surface contacts and trigger follow-up drafts.

---

## Architecture Summary

```
Scraper → Opportunity (with raw_data) 
                ↓
        Contact Extractor (LLM + structured)
                ↓
        contacts table (DB)
                ↓
        Follow-up Drafter (LLM, contact-aware)
                ↓
        API endpoints → Minimal Web UI
```

**New files:**
- `src/emplaiyed/contacts/extractor.py` — LLM-based + scraper-time contact extraction
- `src/emplaiyed/contacts/__init__.py` — package
- `src/emplaiyed/contacts/followup_drafter.py` — contact-aware follow-up content generation
- `src/emplaiyed/api/routes/contacts.py` — API routes for contacts + follow-up drafting
- `src/emplaiyed/web/templates/partials/contact_card.html` — inline contact display partial
- `tests/test_contacts/test_extractor.py` — extractor tests
- `tests/test_contacts/__init__.py` — package
- `tests/test_contacts/test_followup_drafter.py` — drafter tests
- `tests/test_contacts/test_api.py` — API route tests

**Modified files:**
- `src/emplaiyed/core/models.py` — add `Contact` model
- `src/emplaiyed/core/database.py` — add `contacts` table + CRUD
- `src/emplaiyed/sources/talent.py` — extract `contactPoint` from JSON-LD
- `src/emplaiyed/sources/jobbank.py` — parse "How to apply" section
- `src/emplaiyed/llm/config.py` — add `CONTACT_EXTRACTION_MODEL`
- `src/emplaiyed/api/app.py` — register contacts router
- `src/emplaiyed/api/routes/pages.py` — enrich apps with contacts
- `src/emplaiyed/web/templates/partials/app_table.html` — show contact badge

---

## Phase 1: Data Layer

### 1.1: Add Contact model

**File:** `src/emplaiyed/core/models.py`

Add after the `Opportunity` class:

```python
class Contact(BaseModel):
    """A person associated with a job opportunity (recruiter, hiring manager, etc.)."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    opportunity_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    title: str | None = None          # e.g. "Recruiter", "Hiring Manager"
    source: str = "llm"               # "llm", "json_ld", "html_parse", "manual"
    confidence: float = 0.0           # 0.0-1.0, how confident the extraction was
    created_at: datetime = Field(default_factory=datetime.now)
```

### 1.2: Add contacts table + CRUD

**File:** `src/emplaiyed/core/database.py`

Add to `_POST_MIGRATIONS` (idempotent):

```python
"""
CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY,
    opportunity_id  TEXT NOT NULL,
    name            TEXT,
    email           TEXT,
    phone           TEXT,
    title           TEXT,
    source          TEXT NOT NULL DEFAULT 'llm',
    confidence      REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
);
""",
```

Add CRUD functions:

```python
def save_contact(conn: sqlite3.Connection, contact: Contact) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO contacts
            (id, opportunity_id, name, email, phone, title, source, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact.id,
            contact.opportunity_id,
            contact.name,
            contact.email,
            contact.phone,
            contact.title,
            contact.source,
            contact.confidence,
            contact.created_at.isoformat(),
        ),
    )
    conn.commit()


def get_contacts_for_opportunity(
    conn: sqlite3.Connection, opportunity_id: str
) -> list[Contact]:
    rows = conn.execute(
        "SELECT * FROM contacts WHERE opportunity_id = ? ORDER BY confidence DESC",
        (opportunity_id,),
    ).fetchall()
    return [_row_to_contact(row) for row in rows]


def get_contact(conn: sqlite3.Connection, contact_id: str) -> Contact | None:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return _row_to_contact(row) if row else None


def _row_to_contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"],
        opportunity_id=row["opportunity_id"],
        name=row["name"],
        email=row["email"],
        phone=row["phone"],
        title=row["title"],
        source=row["source"],
        confidence=row["confidence"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
```

---

## Phase 2: Contact Extraction

### 2.1: LLM-based extractor

**New file:** `src/emplaiyed/contacts/extractor.py`

This is the main extraction module. It handles both LLM extraction from free text and structured extraction from scraper data.

```python
"""Contact extraction from job postings — LLM and structured approaches."""

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
        None, description="Role/title, e.g. 'Recruiter', 'Hiring Manager', 'HR Director'"
    )
    confidence: float = Field(
        0.0,
        description="0.0-1.0. 1.0 = explicit contact info stated clearly. "
        "0.5 = inferred from context. 0.0 = no contact info found.",
    )
    found: bool = Field(
        False, description="True if any contact information was found"
    )


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

    # Truncate to save tokens — contact info is usually at the top or bottom
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

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def extract_emails_regex(text: str) -> list[str]:
    """Quick regex extraction of email addresses from text.

    Filters out common generic/noreply patterns.
    """
    _GENERIC = {
        "noreply", "no-reply", "donotreply", "info@", "support@",
        "admin@", "postmaster@", "mailer-daemon",
    }
    emails = _EMAIL_RE.findall(text)
    return [
        e for e in emails
        if not any(g in e.lower() for g in _GENERIC)
    ]


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
# Orchestrator — extract + persist
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
    2. Try regex extraction for emails (free).
    3. Try JSON-LD extraction if raw_data has hiringOrganization.
    4. Fall back to LLM extraction from description text.
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
                "LLM contact extraction failed for %s", opportunity.id, exc_info=True
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
```

### 2.2: Add CONTACT_EXTRACTION_MODEL config

**File:** `src/emplaiyed/llm/config.py`

Add after `PROFILE_MODEL`:

```python
CONTACT_EXTRACTION_MODEL = os.environ.get(
    "EMPLAIYED_CONTACT_EXTRACTION_MODEL", "anthropic/claude-haiku-4.5"
)
```

### 2.3: Talent.com structured extraction

**File:** `src/emplaiyed/sources/talent.py`

In `_extract_company()`, capture the full `hiringOrganization` dict and pass it through to `raw_data`. Specifically:

1. Create a new function `_extract_hiring_org(job: dict) -> dict | None` that returns the full `hiringOrganization` dict (not just the name).

2. In `parse_search_results()`, store it in raw_data:
```python
raw_data={
    "job_id": listing["job_id"],
    "hiring_org": _extract_hiring_org(job),  # NEW: preserve for contact extraction
},
```

### 2.4: JobBank "How to apply" extraction

**File:** `src/emplaiyed/sources/jobbank.py`

In `parse_job_posting()`, add parsing of the "How to apply" section before the full-page text extraction. Job Bank Canada uses an `<h3>` or similar heading for "How to apply" with contact details underneath. Add a function:

```python
def _parse_how_to_apply(soup: BeautifulSoup) -> dict:
    """Extract contact info from the 'How to apply' section if present."""
    # Job Bank uses various patterns — look for the section
    how_to = None
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if "how to apply" in heading.get_text(strip=True).lower():
            how_to = heading
            break
    if not how_to:
        return {}

    # Get text between this heading and next heading
    parts = []
    for sib in how_to.find_next_siblings():
        if sib.name in ("h2", "h3", "h4"):
            break
        parts.append(sib.get_text(strip=True))

    text = " ".join(parts)
    return {"how_to_apply_text": text}
```

Store in `raw_data`:
```python
raw_data={
    "job_id": listing["job_id"],
    "salary_text": salary_text,
    "how_to_apply": _parse_how_to_apply(posting_soup),  # NEW
},
```

---

## Phase 3: Contact-Aware Follow-Up Drafter

### 3.1: Follow-up drafter module

**New file:** `src/emplaiyed/contacts/followup_drafter.py`

```python
"""Contact-aware follow-up content generation.

Generates personalized follow-up messages that reference the specific
contact person, their role, and the application history.
"""

from __future__ import annotations

import logging
import sqlite3

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.database import (
    get_contacts_for_opportunity,
    get_opportunity,
    list_interactions,
    list_status_transitions,
)
from emplaiyed.core.models import Application, Contact, Opportunity, Profile
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


class FollowUpContent(BaseModel):
    """Generated follow-up content for a specific contact."""
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Full email body text")
    channel_suggestion: str = Field(
        description="Recommended channel: 'email', 'linkedin', or 'phone'"
    )
    tone_note: str = Field(
        description="Brief note about the tone/approach chosen and why"
    )


_FOLLOWUP_SYSTEM_PROMPT = """\
You write follow-up messages for job applications. Your messages are:
- Professional but warm — you're a real person, not a template
- Brief — under 100 words for the body
- Specific — reference the role, company, and something concrete
- Non-pushy — express continued interest without demanding a response
- Channel-aware — suggest the best way to reach this person

If the contact is a recruiter, be direct and professional.
If the contact is a hiring manager, reference something technical.
If no contact name is known, use "Dear Hiring Team" or similar.

CRITICAL: Write in the same language as the job description. If the job is in \
French, write the follow-up in French.
"""


def _build_followup_prompt(
    profile: Profile,
    opportunity: Opportunity,
    contact: Contact | None,
    application: Application,
    followup_number: int,
    days_since: int,
) -> str:
    """Build the prompt for follow-up content generation."""
    parts = [
        "Generate a follow-up message for this job application.",
        "",
        "## Context",
        f"Candidate: {profile.name}",
        f"Company: {opportunity.company}",
        f"Role: {opportunity.title}",
        f"Days since last contact: {days_since}",
        f"Follow-up number: {followup_number} ({'first' if followup_number == 1 else 'second and final'})",
    ]

    if contact:
        parts.append(f"\n## Contact Person")
        if contact.name:
            parts.append(f"Name: {contact.name}")
        if contact.title:
            parts.append(f"Role: {contact.title}")
        if contact.email:
            parts.append(f"Email: {contact.email}")
        if contact.phone:
            parts.append(f"Phone: {contact.phone}")
    else:
        parts.append("\n## Contact Person")
        parts.append("No specific contact identified. Address to hiring team.")

    if profile.skills:
        parts.append(f"\nCandidate skills: {', '.join(profile.skills[:8])}")

    if profile.aspirations and profile.aspirations.statement:
        parts.append(f"Career focus: {profile.aspirations.statement}")

    # Include a snippet of the job description for context
    desc_snippet = opportunity.description[:500] if opportunity.description else ""
    if desc_snippet:
        parts.append(f"\n## Job Description (snippet)")
        parts.append(desc_snippet)

    if followup_number == 2:
        parts.append(
            "\nIMPORTANT: This is the FINAL follow-up. Make it count but keep it "
            "graceful — leave the door open without being desperate."
        )

    return "\n".join(parts)


async def draft_contact_followup(
    profile: Profile,
    opportunity: Opportunity,
    application: Application,
    contact: Contact | None,
    *,
    followup_number: int = 1,
    days_since: int = 5,
    _model_override: Model | None = None,
) -> FollowUpContent:
    """Generate a personalized follow-up for a specific contact.

    Parameters
    ----------
    profile: Candidate profile.
    opportunity: The job opportunity.
    application: The application being followed up on.
    contact: The contact person (or None for generic follow-up).
    followup_number: 1 for first follow-up, 2 for second.
    days_since: Days since last contact.
    _model_override: Inject TestModel for tests.
    """
    from emplaiyed.llm.config import OUTREACH_MODEL

    prompt = _build_followup_prompt(
        profile, opportunity, contact, application,
        followup_number, days_since,
    )

    return await complete_structured(
        prompt,
        FollowUpContent,
        system_prompt=_FOLLOWUP_SYSTEM_PROMPT,
        model=OUTREACH_MODEL,
        _model_override=_model_override,
    )
```

---

## Phase 4: API Endpoints

### 4.1: Contacts API routes

**New file:** `src/emplaiyed/api/routes/contacts.py`

```python
"""API routes for contact extraction and follow-up drafting."""

from __future__ import annotations

import asyncio
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from emplaiyed.api.deps import get_db, get_profile
from emplaiyed.core.database import (
    get_application,
    get_contacts_for_opportunity,
    get_opportunity,
)
from emplaiyed.core.models import Profile

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("/{opportunity_id}")
def list_contacts(
    opportunity_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Get all contacts for an opportunity."""
    contacts = get_contacts_for_opportunity(conn, opportunity_id)
    return [c.model_dump() for c in contacts]


@router.post("/{opportunity_id}/extract")
async def extract_contacts(
    opportunity_id: str,
    force: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Extract contacts from an opportunity's description."""
    from emplaiyed.contacts.extractor import extract_and_save_contacts

    opp = get_opportunity(conn, opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    contacts = await extract_and_save_contacts(conn, opp, force=force)
    return [c.model_dump() for c in contacts]


@router.post("/draft-followup/{application_id}")
async def draft_followup(
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    profile: Profile | None = Depends(get_profile),
):
    """Generate a follow-up draft for an application, targeted at the best contact."""
    from datetime import datetime

    from emplaiyed.contacts.followup_drafter import draft_contact_followup

    if not profile:
        raise HTTPException(status_code=400, detail="No profile found")

    app = get_application(conn, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    opp = get_opportunity(conn, app.opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    # Get best contact (highest confidence)
    contacts = get_contacts_for_opportunity(conn, opp.id)
    contact = contacts[0] if contacts else None

    # Determine follow-up number from current status
    followup_number = 1
    if app.status.value in ("FOLLOW_UP_1",):
        followup_number = 2

    days_since = (datetime.now() - app.updated_at).days

    draft = await draft_contact_followup(
        profile, opp, app, contact,
        followup_number=followup_number,
        days_since=max(days_since, 1),
    )

    return {
        "draft": draft.model_dump(),
        "contact": contact.model_dump() if contact else None,
    }
```

### 4.2: Register router

**File:** `src/emplaiyed/api/app.py`

Add to the router includes:

```python
from emplaiyed.api.routes.contacts import router as contacts_router
app.include_router(contacts_router)
```

### 4.3: Enrich app table with contacts

**File:** `src/emplaiyed/api/routes/pages.py`

Update `_enrich_applications()` to include contact data:

```python
def _enrich_applications(conn: sqlite3.Connection, applications: list) -> list[dict]:
    """Attach opportunity and contact data to each application for display."""
    from emplaiyed.core.database import get_contacts_for_opportunity

    enriched = []
    for app in applications:
        opp = get_opportunity(conn, app.opportunity_id)
        contacts = get_contacts_for_opportunity(conn, opp.id) if opp else []
        enriched.append(
            {
                "app": app,
                "opp": opp,
                "contact": contacts[0] if contacts else None,
            }
        )
    return enriched
```

---

## Phase 5: Minimal Web UI

### 5.1: Contact badge in app table

**File:** `src/emplaiyed/web/templates/partials/app_table.html`

Add a contact column or badge to each row. When a contact exists, show the name/email. When none exists, show an "Extract" button that calls the extract endpoint via htmx.

```html
<!-- In the table row, after the status column -->
<td class="text-xs">
  {% if item.contact %}
    <div class="flex items-center gap-1">
      <span class="badge badge-sm badge-success badge-outline">
        {{ item.contact.name or item.contact.email or 'Contact found' }}
      </span>
    </div>
  {% else %}
    <button
      class="btn btn-xs btn-ghost"
      hx-post="/api/contacts/{{ item.opp.id }}/extract"
      hx-target="closest td"
      hx-swap="innerHTML"
      hx-indicator="closest tr"
    >
      Extract
    </button>
  {% endif %}
</td>
```

### 5.2: Contact card partial

**New file:** `src/emplaiyed/web/templates/partials/contact_card.html`

A small reusable partial for displaying contact info with a "Draft Follow-up" button:

```html
<div class="card card-compact bg-base-200 shadow-sm">
  <div class="card-body">
    {% if contact %}
      <h3 class="card-title text-sm">
        {{ contact.name or 'Unknown Contact' }}
        {% if contact.title %}
          <span class="badge badge-sm badge-ghost">{{ contact.title }}</span>
        {% endif %}
      </h3>
      {% if contact.email %}
        <p class="text-xs"><span class="font-mono">{{ contact.email }}</span></p>
      {% endif %}
      {% if contact.phone %}
        <p class="text-xs">{{ contact.phone }}</p>
      {% endif %}
      <p class="text-xs opacity-50">
        Source: {{ contact.source }} | Confidence: {{ (contact.confidence * 100)|int }}%
      </p>
    {% else %}
      <p class="text-xs opacity-50">No contact found</p>
    {% endif %}
    {% if application_id %}
      <div class="card-actions justify-end mt-2">
        <button
          class="btn btn-xs btn-primary"
          hx-post="/api/contacts/draft-followup/{{ application_id }}"
          hx-target="#followup-draft-{{ application_id }}"
          hx-swap="innerHTML"
          hx-indicator="this"
        >
          Draft Follow-up
        </button>
      </div>
      <div id="followup-draft-{{ application_id }}" class="mt-2"></div>
    {% endif %}
  </div>
</div>
```

### 5.3: Follow-up draft response partial

The `draft-followup` endpoint should return an HTML partial (not JSON) when called from htmx. Add an `Accept` header check or a dedicated HTML endpoint:

**File:** `src/emplaiyed/api/routes/contacts.py`

Add an HTML-returning endpoint for htmx:

```python
from fastapi.responses import HTMLResponse

@router.post("/draft-followup/{application_id}/html")
async def draft_followup_html(
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    profile: Profile | None = Depends(get_profile),
):
    """Generate follow-up and return as an HTML partial for htmx."""
    # ... same logic as draft_followup ...
    # Return rendered HTML with the draft content
```

---

## Phase 6: Tests

### 6.1: Extractor tests

**New file:** `tests/test_contacts/test_extractor.py`

Test cases:
- `test_extract_contact_llm_returns_model` — TestModel returns ExtractedContact
- `test_extract_emails_regex_finds_emails` — regex finds standard emails
- `test_extract_emails_regex_filters_generic` — filters noreply, info@, etc.
- `test_extract_contact_jsonld_with_contact_point` — parses schema.org contactPoint
- `test_extract_contact_jsonld_no_contact` — returns None when no contact
- `test_extract_and_save_contacts_llm_path` — orchestrator uses LLM when no structured data
- `test_extract_and_save_contacts_skips_existing` — doesn't re-extract if contacts exist
- `test_extract_and_save_contacts_force` — re-extracts even with existing contacts
- `test_extract_and_save_contacts_regex_fallback` — uses regex when LLM finds nothing

### 6.2: Follow-up drafter tests

**New file:** `tests/test_contacts/test_followup_drafter.py`

Test cases:
- `test_build_followup_prompt_with_contact` — prompt includes contact name/email
- `test_build_followup_prompt_without_contact` — prompt says "address to hiring team"
- `test_build_followup_prompt_second_followup` — includes "FINAL follow-up" guidance
- `test_draft_contact_followup_returns_model` — TestModel returns FollowUpContent
- `test_draft_includes_channel_suggestion` — output has channel_suggestion field

### 6.3: API tests

**New file:** `tests/test_contacts/test_api.py`

Test the FastAPI endpoints using TestClient with a test DB.

---

## Summary of Changes

| Phase | File | Type | Description |
|-------|------|------|-------------|
| 1 | `core/models.py` | Edit | Add `Contact` model |
| 1 | `core/database.py` | Edit | Add `contacts` table, CRUD functions |
| 2 | `contacts/__init__.py` | New | Package marker |
| 2 | `contacts/extractor.py` | New | LLM + structured + regex contact extraction |
| 2 | `llm/config.py` | Edit | Add `CONTACT_EXTRACTION_MODEL` |
| 2 | `sources/talent.py` | Edit | Preserve hiringOrganization in raw_data |
| 2 | `sources/jobbank.py` | Edit | Parse "How to apply" section |
| 3 | `contacts/followup_drafter.py` | New | Contact-aware follow-up generation |
| 4 | `api/routes/contacts.py` | New | API routes for contacts + drafting |
| 4 | `api/app.py` | Edit | Register contacts router |
| 4 | `api/routes/pages.py` | Edit | Enrich apps with contact data |
| 5 | `web/templates/partials/app_table.html` | Edit | Contact badge + extract button |
| 5 | `web/templates/partials/contact_card.html` | New | Contact display + draft button |
| 6 | `tests/test_contacts/__init__.py` | New | Package marker |
| 6 | `tests/test_contacts/test_extractor.py` | New | Extractor tests |
| 6 | `tests/test_contacts/test_followup_drafter.py` | New | Drafter tests |
| 6 | `tests/test_contacts/test_api.py` | New | API route tests |
