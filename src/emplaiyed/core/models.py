from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models (used inside Profile)
# ---------------------------------------------------------------------------

class Address(BaseModel):
    street: str | None = None
    city: str | None = None
    province_state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class Language(BaseModel):
    language: str
    proficiency: str


class Education(BaseModel):
    institution: str
    degree: str
    field: str
    start_date: date | None = None
    end_date: date | None = None


class Employment(BaseModel):
    company: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)


class Certification(BaseModel):
    name: str
    issuer: str
    date_obtained: date | None = None
    expiry_date: date | None = None


class Aspirations(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    salary_minimum: int | None = None
    salary_target: int | None = None
    urgency: str | None = None
    geographic_preferences: list[str] = Field(default_factory=list)
    work_arrangement: list[str] = Field(default_factory=list)
    statement: str | None = None


class SmtpConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str
    from_address: str


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class Profile(BaseModel):
    name: str
    email: str
    phone: str | None = None
    date_of_birth: date | None = None
    address: Address | None = None
    skills: list[str] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    employment_history: list[Employment] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    aspirations: Aspirations | None = None
    smtp_config: SmtpConfig | None = None


# ---------------------------------------------------------------------------
# Opportunity pipeline
# ---------------------------------------------------------------------------

class Opportunity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    source_url: str | None = None
    company: str
    title: str
    description: str
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    posted_date: date | None = None
    scraped_at: datetime
    raw_data: dict | None = None


class ScoredOpportunity(BaseModel):
    opportunity: Opportunity
    score: int = Field(ge=0, le=100)
    justification: str
    day_to_day: str = ""
    why_it_fits: str = ""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    SCORED = "SCORED"
    OUTREACH_PENDING = "OUTREACH_PENDING"
    OUTREACH_SENT = "OUTREACH_SENT"
    FOLLOW_UP_PENDING = "FOLLOW_UP_PENDING"
    FOLLOW_UP_1 = "FOLLOW_UP_1"
    FOLLOW_UP_2 = "FOLLOW_UP_2"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    NEGOTIATION_PENDING = "NEGOTIATION_PENDING"
    NEGOTIATING = "NEGOTIATING"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    GHOSTED = "GHOSTED"
    PASSED = "PASSED"


class InteractionType(str, enum.Enum):
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_RECEIVED = "EMAIL_RECEIVED"
    LINKEDIN_MESSAGE = "LINKEDIN_MESSAGE"
    PHONE_CALL = "PHONE_CALL"
    FORM_SUBMITTED = "FORM_SUBMITTED"
    INTERVIEW = "INTERVIEW"
    NOTE = "NOTE"
    FOLLOW_UP = "FOLLOW_UP"


class OfferStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    COUNTERED = "COUNTERED"


# ---------------------------------------------------------------------------
# Application / Interaction / Offer
# ---------------------------------------------------------------------------

class Application(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    opportunity_id: str
    status: ApplicationStatus
    score: int | None = None
    justification: str | None = None
    day_to_day: str | None = None
    why_it_fits: str | None = None
    created_at: datetime
    updated_at: datetime


class Interaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    application_id: str
    type: InteractionType
    direction: str
    channel: str
    content: str | None = None
    metadata: dict | None = None
    created_at: datetime


class Offer(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    application_id: str
    salary: int | None = None
    currency: str = "CAD"
    benefits: str | None = None
    conditions: str | None = None
    start_date: date | None = None
    deadline: date | None = None
    status: OfferStatus
    created_at: datetime


# ---------------------------------------------------------------------------
# Scheduled Event
# ---------------------------------------------------------------------------

class ScheduledEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    application_id: str
    event_type: str  # "phone_screen", "technical_interview", "onsite", "follow_up_due", etc.
    scheduled_date: datetime
    notes: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Work Queue
# ---------------------------------------------------------------------------


class WorkType(str, enum.Enum):
    OUTREACH = "OUTREACH"
    FOLLOW_UP = "FOLLOW_UP"
    NEGOTIATE = "NEGOTIATE"
    ACCEPT = "ACCEPT"


class WorkStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class WorkItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    application_id: str
    work_type: WorkType
    status: WorkStatus = WorkStatus.PENDING
    title: str
    instructions: str
    draft_content: str | None = None
    target_status: str  # ApplicationStatus value to transition to on "done"
    previous_status: str  # ApplicationStatus value to revert to on "skip"
    created_at: datetime
    completed_at: datetime | None = None
