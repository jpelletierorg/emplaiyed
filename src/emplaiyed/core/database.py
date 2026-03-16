from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Contact,
    Interaction,
    InteractionType,
    Offer,
    OfferStatus,
    Opportunity,
    ScheduledEvent,
    StatusTransition,
    WorkItem,
    WorkStatus,
    WorkType,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_url  TEXT,
    company     TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    location    TEXT,
    salary_min  INTEGER,
    salary_max  INTEGER,
    posted_date TEXT,
    scraped_at  TEXT NOT NULL,
    raw_data    TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id              TEXT PRIMARY KEY,
    opportunity_id  TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
);

CREATE TABLE IF NOT EXISTS interactions (
    id              TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL,
    type            TEXT NOT NULL,
    direction       TEXT NOT NULL,
    channel         TEXT NOT NULL,
    content         TEXT,
    metadata        TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS offers (
    id              TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL,
    salary          INTEGER,
    currency        TEXT NOT NULL DEFAULT 'CAD',
    benefits        TEXT,
    conditions      TEXT,
    start_date      TEXT,
    deadline        TEXT,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS scheduled_events (
    id              TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    scheduled_date  TEXT NOT NULL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS work_items (
    id              TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL,
    work_type       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    title           TEXT NOT NULL,
    instructions    TEXT NOT NULL,
    draft_content   TEXT,
    target_status   TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);
"""

_MIGRATIONS = [
    "ALTER TABLE applications ADD COLUMN score INTEGER",
    "ALTER TABLE applications ADD COLUMN justification TEXT",
    "ALTER TABLE applications ADD COLUMN day_to_day TEXT",
    "ALTER TABLE applications ADD COLUMN why_it_fits TEXT",
    "ALTER TABLE opportunities ADD COLUMN short_id TEXT",
]

_POST_MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS status_history (
        id                TEXT PRIMARY KEY,
        application_id    TEXT NOT NULL,
        from_status       TEXT NOT NULL,
        to_status         TEXT NOT NULL,
        transitioned_at   TEXT NOT NULL,
        FOREIGN KEY (application_id) REFERENCES applications(id)
    )
    """,
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processed_emails (
        id              TEXT PRIMARY KEY,
        message_id      TEXT NOT NULL UNIQUE,
        from_address    TEXT,
        subject         TEXT,
        received_at     TEXT,
        category        TEXT,
        matched_app_id  TEXT,
        summary         TEXT,
        processed_at    TEXT NOT NULL
    )
    """,
    # Full-text search index on opportunities for quick keyword lookup.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS opportunities_fts
    USING fts5(opp_id UNINDEXED, company, title, description, location)
    """,
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _date_to_str(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _datetime_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _str_to_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _str_to_datetime(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _json_dumps(obj: Any | None) -> str | None:
    return json.dumps(obj) if obj is not None else None


def _json_loads(s: str | None) -> Any | None:
    return json.loads(s) if s else None


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def init_db(path: Path) -> sqlite3.Connection:
    """Create / open the SQLite database and ensure all tables exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(_SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    for stmt in _POST_MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # table already exists or DB is locked by another process
    conn.commit()
    return conn


def get_default_db_path() -> Path:
    """Return ``data/emplaiyed.db`` relative to the project root."""
    from emplaiyed.core.paths import find_project_root

    return find_project_root() / "data" / "emplaiyed.db"


# ---------------------------------------------------------------------------
# Opportunity CRUD
# ---------------------------------------------------------------------------


def save_opportunity(conn: sqlite3.Connection, opportunity: Opportunity) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO opportunities
            (id, short_id, source, source_url, company, title, description,
             location, salary_min, salary_max, posted_date, scraped_at, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opportunity.id,
            opportunity.short_id,
            opportunity.source,
            opportunity.source_url,
            opportunity.company,
            opportunity.title,
            opportunity.description,
            opportunity.location,
            opportunity.salary_min,
            opportunity.salary_max,
            _date_to_str(opportunity.posted_date),
            _datetime_to_str(opportunity.scraped_at),
            _json_dumps(opportunity.raw_data),
        ),
    )
    # Keep FTS index in sync — delete stale row (if any) then insert fresh.
    conn.execute("DELETE FROM opportunities_fts WHERE opp_id = ?", (opportunity.id,))
    conn.execute(
        """
        INSERT INTO opportunities_fts (opp_id, company, title, description, location)
        VALUES (?, ?, ?, COALESCE(?, ''), COALESCE(?, ''))
        """,
        (
            opportunity.id,
            opportunity.company,
            opportunity.title,
            opportunity.description,
            opportunity.location,
        ),
    )
    conn.commit()


def _row_to_opportunity(row: sqlite3.Row) -> Opportunity:
    # short_id may be NULL for opportunities created before the migration.
    # In that case, generate one and let it persist on next save.
    from emplaiyed.core.models import _generate_short_id

    short_id = row["short_id"] if "short_id" in row.keys() else None
    return Opportunity(
        id=row["id"],
        short_id=short_id or _generate_short_id(),
        source=row["source"],
        source_url=row["source_url"],
        company=row["company"],
        title=row["title"],
        description=row["description"],
        location=row["location"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        posted_date=_str_to_date(row["posted_date"]),
        scraped_at=_str_to_datetime(row["scraped_at"]),  # type: ignore[arg-type]
        raw_data=_json_loads(row["raw_data"]),
    )


def get_opportunity(conn: sqlite3.Connection, id: str) -> Opportunity | None:
    cur = conn.execute("SELECT * FROM opportunities WHERE id = ?", (id,))
    row = cur.fetchone()
    return _row_to_opportunity(row) if row else None


def get_opportunity_by_short_id(
    conn: sqlite3.Connection, short_id: str
) -> Opportunity | None:
    """Look up an opportunity by its 6-character short_id."""
    cur = conn.execute("SELECT * FROM opportunities WHERE short_id = ?", (short_id,))
    row = cur.fetchone()
    return _row_to_opportunity(row) if row else None


def list_opportunities(conn: sqlite3.Connection, **filters: Any) -> list[Opportunity]:
    query = "SELECT * FROM opportunities"
    params: list[Any] = []
    clauses: list[str] = []

    for col, val in filters.items():
        clauses.append(f"{col} = ?")
        params.append(val)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY scraped_at DESC"
    cur = conn.execute(query, params)
    return [_row_to_opportunity(row) for row in cur.fetchall()]


def active_opportunity_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """Return (company, title, source) keys for opportunities that already have applications.

    Any opportunity with an existing application — regardless of status — is
    excluded from re-discovery.  Once you've seen it (scored, passed, rejected,
    ghosted, etc.) it should not reappear as new.
    """
    cur = conn.execute(
        """
        SELECT DISTINCT lower(o.company), lower(o.title), lower(o.source)
        FROM opportunities o
        JOIN applications a ON a.opportunity_id = o.id
        """
    )
    return {(row[0], row[1], row[2]) for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Application CRUD
# ---------------------------------------------------------------------------


def save_application(conn: sqlite3.Connection, application: Application) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO applications
            (id, opportunity_id, status, score, justification,
             day_to_day, why_it_fits, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application.id,
            application.opportunity_id,
            application.status.value,
            application.score,
            application.justification,
            application.day_to_day,
            application.why_it_fits,
            _datetime_to_str(application.created_at),
            _datetime_to_str(application.updated_at),
        ),
    )
    conn.commit()


def _row_to_application(row: sqlite3.Row) -> Application:
    return Application(
        id=row["id"],
        opportunity_id=row["opportunity_id"],
        status=ApplicationStatus(row["status"]),
        score=row["score"],
        justification=row["justification"],
        day_to_day=row["day_to_day"],
        why_it_fits=row["why_it_fits"],
        created_at=_str_to_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=_str_to_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


def get_application(conn: sqlite3.Connection, id: str) -> Application | None:
    cur = conn.execute("SELECT * FROM applications WHERE id = ?", (id,))
    row = cur.fetchone()
    return _row_to_application(row) if row else None


def list_applications(conn: sqlite3.Connection, **filters: Any) -> list[Application]:
    query = "SELECT * FROM applications"
    params: list[Any] = []
    clauses: list[str] = []

    for col, val in filters.items():
        if col == "status" and isinstance(val, ApplicationStatus):
            clauses.append("status = ?")
            params.append(val.value)
        else:
            clauses.append(f"{col} = ?")
            params.append(val)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY updated_at DESC"
    cur = conn.execute(query, params)
    return [_row_to_application(row) for row in cur.fetchall()]


def delete_application(conn: sqlite3.Connection, application_id: str) -> None:
    """Delete an application and all related data (cascading).

    Removes: interactions, offers, scheduled_events, work_items,
    status_history, and the application itself.  Also deletes the
    opportunity if no other applications reference it.
    """
    conn.execute("DELETE FROM interactions WHERE application_id = ?", (application_id,))
    conn.execute("DELETE FROM offers WHERE application_id = ?", (application_id,))
    conn.execute(
        "DELETE FROM scheduled_events WHERE application_id = ?", (application_id,)
    )
    conn.execute("DELETE FROM work_items WHERE application_id = ?", (application_id,))
    conn.execute(
        "DELETE FROM status_history WHERE application_id = ?", (application_id,)
    )

    # Find the opportunity before deleting the application
    cur = conn.execute(
        "SELECT opportunity_id FROM applications WHERE id = ?", (application_id,)
    )
    row = cur.fetchone()
    opp_id = row["opportunity_id"] if row else None

    conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))

    # Delete orphaned opportunity (no other applications reference it)
    if opp_id:
        cur = conn.execute(
            "SELECT COUNT(*) as cnt FROM applications WHERE opportunity_id = ?",
            (opp_id,),
        )
        if cur.fetchone()["cnt"] == 0:
            conn.execute("DELETE FROM opportunities WHERE id = ?", (opp_id,))

    conn.commit()


# ---------------------------------------------------------------------------
# Interaction CRUD
# ---------------------------------------------------------------------------


def save_interaction(conn: sqlite3.Connection, interaction: Interaction) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO interactions
            (id, application_id, type, direction, channel, content, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            interaction.id,
            interaction.application_id,
            interaction.type.value,
            interaction.direction,
            interaction.channel,
            interaction.content,
            _json_dumps(interaction.metadata),
            _datetime_to_str(interaction.created_at),
        ),
    )
    conn.commit()


def _row_to_interaction(row: sqlite3.Row) -> Interaction:
    return Interaction(
        id=row["id"],
        application_id=row["application_id"],
        type=InteractionType(row["type"]),
        direction=row["direction"],
        channel=row["channel"],
        content=row["content"],
        metadata=_json_loads(row["metadata"]),
        created_at=_str_to_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


def list_interactions(
    conn: sqlite3.Connection, application_id: str
) -> list[Interaction]:
    cur = conn.execute(
        "SELECT * FROM interactions WHERE application_id = ? ORDER BY created_at",
        (application_id,),
    )
    return [_row_to_interaction(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Offer CRUD
# ---------------------------------------------------------------------------


def save_offer(conn: sqlite3.Connection, offer: Offer) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO offers
            (id, application_id, salary, currency, benefits, conditions,
             start_date, deadline, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            offer.id,
            offer.application_id,
            offer.salary,
            offer.currency,
            offer.benefits,
            offer.conditions,
            _date_to_str(offer.start_date),
            _date_to_str(offer.deadline),
            offer.status.value,
            _datetime_to_str(offer.created_at),
        ),
    )
    conn.commit()


def _row_to_offer(row: sqlite3.Row) -> Offer:
    return Offer(
        id=row["id"],
        application_id=row["application_id"],
        salary=row["salary"],
        currency=row["currency"],
        benefits=row["benefits"],
        conditions=row["conditions"],
        start_date=_str_to_date(row["start_date"]),
        deadline=_str_to_date(row["deadline"]),
        status=OfferStatus(row["status"]),
        created_at=_str_to_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


def get_offer(conn: sqlite3.Connection, id: str) -> Offer | None:
    cur = conn.execute("SELECT * FROM offers WHERE id = ?", (id,))
    row = cur.fetchone()
    return _row_to_offer(row) if row else None


def list_offers(conn: sqlite3.Connection, **filters: Any) -> list[Offer]:
    query = "SELECT * FROM offers"
    params: list[Any] = []
    clauses: list[str] = []

    for col, val in filters.items():
        if col == "status" and isinstance(val, OfferStatus):
            clauses.append("status = ?")
            params.append(val.value)
        else:
            clauses.append(f"{col} = ?")
            params.append(val)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY created_at DESC"
    cur = conn.execute(query, params)
    return [_row_to_offer(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Scheduled Event CRUD
# ---------------------------------------------------------------------------


def save_event(conn: sqlite3.Connection, event: ScheduledEvent) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO scheduled_events
            (id, application_id, event_type, scheduled_date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.application_id,
            event.event_type,
            _datetime_to_str(event.scheduled_date),
            event.notes,
            _datetime_to_str(event.created_at),
        ),
    )
    conn.commit()


def _row_to_event(row: sqlite3.Row) -> ScheduledEvent:
    return ScheduledEvent(
        id=row["id"],
        application_id=row["application_id"],
        event_type=row["event_type"],
        scheduled_date=_str_to_datetime(row["scheduled_date"]),  # type: ignore[arg-type]
        notes=row["notes"],
        created_at=_str_to_datetime(row["created_at"]),  # type: ignore[arg-type]
    )


def get_event(conn: sqlite3.Connection, id: str) -> ScheduledEvent | None:
    cur = conn.execute("SELECT * FROM scheduled_events WHERE id = ?", (id,))
    row = cur.fetchone()
    return _row_to_event(row) if row else None


def list_events(conn: sqlite3.Connection, **filters: Any) -> list[ScheduledEvent]:
    query = "SELECT * FROM scheduled_events"
    params: list[Any] = []
    clauses: list[str] = []

    for col, val in filters.items():
        if col == "date_from":
            clauses.append("scheduled_date >= ?")
            params.append(_datetime_to_str(val))
        elif col == "date_to":
            clauses.append("scheduled_date <= ?")
            params.append(_datetime_to_str(val))
        else:
            clauses.append(f"{col} = ?")
            params.append(val)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY scheduled_date ASC"
    cur = conn.execute(query, params)
    return [_row_to_event(row) for row in cur.fetchall()]


def list_upcoming_events(conn: sqlite3.Connection) -> list[ScheduledEvent]:
    """Return events from now onwards, sorted by scheduled date."""
    now = _datetime_to_str(datetime.now())
    cur = conn.execute(
        "SELECT * FROM scheduled_events WHERE scheduled_date >= ? ORDER BY scheduled_date ASC",
        (now,),
    )
    return [_row_to_event(row) for row in cur.fetchall()]


def delete_event(conn: sqlite3.Connection, id: str) -> None:
    conn.execute("DELETE FROM scheduled_events WHERE id = ?", (id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Work Item CRUD
# ---------------------------------------------------------------------------


def save_work_item(conn: sqlite3.Connection, item: WorkItem) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO work_items
            (id, application_id, work_type, status, title, instructions,
             draft_content, target_status, previous_status, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            item.application_id,
            item.work_type.value,
            item.status.value,
            item.title,
            item.instructions,
            item.draft_content,
            item.target_status,
            item.previous_status,
            _datetime_to_str(item.created_at),
            _datetime_to_str(item.completed_at),
        ),
    )
    conn.commit()


def _row_to_work_item(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        id=row["id"],
        application_id=row["application_id"],
        work_type=WorkType(row["work_type"]),
        status=WorkStatus(row["status"]),
        title=row["title"],
        instructions=row["instructions"],
        draft_content=row["draft_content"],
        target_status=row["target_status"],
        previous_status=row["previous_status"],
        created_at=_str_to_datetime(row["created_at"]),  # type: ignore[arg-type]
        completed_at=_str_to_datetime(row["completed_at"]),
    )


def get_work_item(conn: sqlite3.Connection, id: str) -> WorkItem | None:
    cur = conn.execute("SELECT * FROM work_items WHERE id = ?", (id,))
    row = cur.fetchone()
    return _row_to_work_item(row) if row else None


def list_work_items(conn: sqlite3.Connection, **filters: Any) -> list[WorkItem]:
    query = "SELECT * FROM work_items"
    params: list[Any] = []
    clauses: list[str] = []

    for col, val in filters.items():
        if col == "status" and isinstance(val, WorkStatus):
            clauses.append("status = ?")
            params.append(val.value)
        elif col == "work_type" and isinstance(val, WorkType):
            clauses.append("work_type = ?")
            params.append(val.value)
        else:
            clauses.append(f"{col} = ?")
            params.append(val)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY created_at ASC"
    cur = conn.execute(query, params)
    return [_row_to_work_item(row) for row in cur.fetchall()]


def list_pending_work_items(conn: sqlite3.Connection) -> list[WorkItem]:
    """Return all PENDING work items, oldest first."""
    return list_work_items(conn, status=WorkStatus.PENDING)


# ---------------------------------------------------------------------------
# Status History CRUD
# ---------------------------------------------------------------------------


def save_status_transition(conn: sqlite3.Connection, t: StatusTransition) -> None:
    conn.execute(
        """
        INSERT INTO status_history
            (id, application_id, from_status, to_status, transitioned_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            t.id,
            t.application_id,
            t.from_status,
            t.to_status,
            _datetime_to_str(t.transitioned_at),
        ),
    )
    conn.commit()


def _row_to_status_transition(row: sqlite3.Row) -> StatusTransition:
    return StatusTransition(
        id=row["id"],
        application_id=row["application_id"],
        from_status=row["from_status"],
        to_status=row["to_status"],
        transitioned_at=_str_to_datetime(row["transitioned_at"]),  # type: ignore[arg-type]
    )


def list_status_transitions(
    conn: sqlite3.Connection, application_id: str
) -> list[StatusTransition]:
    """Return all status transitions for an application, oldest first."""
    cur = conn.execute(
        "SELECT * FROM status_history WHERE application_id = ? ORDER BY transitioned_at ASC",
        (application_id,),
    )
    return [_row_to_status_transition(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Multi-status application query
# ---------------------------------------------------------------------------


def list_applications_by_statuses(
    conn: sqlite3.Connection, statuses: list[ApplicationStatus]
) -> list[Application]:
    """Return applications whose status is in the given list, ordered by updated_at DESC."""
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    query = f"SELECT * FROM applications WHERE status IN ({placeholders}) ORDER BY updated_at DESC"
    params = [s.value for s in statuses]
    cur = conn.execute(query, params)
    return [_row_to_application(row) for row in cur.fetchall()]


def reclassify_threshold_apps(conn: sqlite3.Connection, threshold: int) -> int:
    """Re-classify SCORED / BELOW_THRESHOLD apps based on *threshold*.

    * SCORED apps with ``score < threshold`` → BELOW_THRESHOLD
    * BELOW_THRESHOLD apps with ``score >= threshold`` → SCORED

    Returns the total number of applications whose status changed.
    """
    now = _datetime_to_str(datetime.now())

    # Demote: SCORED → BELOW_THRESHOLD
    cur = conn.execute(
        """
        UPDATE applications
           SET status = ?, updated_at = ?
         WHERE status = ? AND score IS NOT NULL AND score < ?
        """,
        (
            ApplicationStatus.BELOW_THRESHOLD.value,
            now,
            ApplicationStatus.SCORED.value,
            threshold,
        ),
    )
    demoted = cur.rowcount

    # Promote: BELOW_THRESHOLD → SCORED
    cur = conn.execute(
        """
        UPDATE applications
           SET status = ?, updated_at = ?
         WHERE status = ? AND (score IS NULL OR score >= ?)
        """,
        (
            ApplicationStatus.SCORED.value,
            now,
            ApplicationStatus.BELOW_THRESHOLD.value,
            threshold,
        ),
    )
    promoted = cur.rowcount

    if demoted or promoted:
        conn.commit()

    return demoted + promoted


# ---------------------------------------------------------------------------
# Contact CRUD
# ---------------------------------------------------------------------------


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


def delete_contacts_for_opportunity(
    conn: sqlite3.Connection, opportunity_id: str
) -> None:
    conn.execute("DELETE FROM contacts WHERE opportunity_id = ?", (opportunity_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Processed Email CRUD
# ---------------------------------------------------------------------------


def is_email_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    """Return True if a message_id has already been processed."""
    cur = conn.execute(
        "SELECT 1 FROM processed_emails WHERE message_id = ?", (message_id,)
    )
    return cur.fetchone() is not None


def save_processed_email(
    conn: sqlite3.Connection,
    *,
    id: str,
    message_id: str,
    from_address: str | None,
    subject: str | None,
    received_at: str | None,
    category: str | None,
    matched_app_id: str | None,
    summary: str | None,
    processed_at: str,
) -> None:
    """Record an email as processed (idempotent via UNIQUE on message_id)."""
    conn.execute(
        """
        INSERT OR REPLACE INTO processed_emails
            (id, message_id, from_address, subject, received_at,
             category, matched_app_id, summary, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            id,
            message_id,
            from_address,
            subject,
            received_at,
            category,
            matched_app_id,
            summary,
            processed_at,
        ),
    )
    conn.commit()


def list_processed_emails(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict]:
    """Return recent processed emails as dicts, newest first."""
    cur = conn.execute(
        "SELECT * FROM processed_emails ORDER BY processed_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------


def rebuild_search_index(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS5 search index from the opportunities table.

    Safe to call repeatedly — clears and repopulates every time.
    Should be called after bulk inserts (scan, search agent, etc.).
    """
    conn.execute("DELETE FROM opportunities_fts")
    conn.execute(
        """
        INSERT INTO opportunities_fts (opp_id, company, title, description, location)
        SELECT id, company, title, COALESCE(description, ''), COALESCE(location, '')
        FROM opportunities
        """
    )
    conn.commit()


def search_opportunities(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[tuple[Opportunity, Application | None]]:
    """Full-text search over opportunities, joined with their application.

    Returns up to *limit* ``(Opportunity, Application | None)`` tuples
    ranked by BM25 relevance.  The query string uses FTS5 syntax — plain
    words are implicitly ANDed, ``*`` for prefix, ``"`` for phrases.

    If the FTS table is empty or the query matches nothing, returns ``[]``.
    """
    query = query.strip()
    if not query:
        return []

    # Lazy-populate: rebuild the index on first search if it's empty but
    # opportunities exist.  This covers the case where the DB was created
    # before FTS was added, or after init_db (which intentionally does NOT
    # rebuild to avoid locking issues in concurrent environments).
    fts_count = conn.execute("SELECT COUNT(*) FROM opportunities_fts").fetchone()[0]
    if fts_count == 0:
        opp_count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        if opp_count > 0:
            rebuild_search_index(conn)

    # Tokenise into words and add implicit prefix wildcard to the last term
    # so that partial typing works (e.g. "devops chat" → "devops chat*").
    tokens = query.split()
    fts_query = " ".join(tokens[:-1] + [tokens[-1] + "*"]) if tokens else query

    try:
        cur = conn.execute(
            """
            SELECT
                o.*,
                a.id            AS app_id,
                a.status        AS app_status,
                a.score         AS app_score,
                a.justification AS app_justification,
                a.day_to_day    AS app_day_to_day,
                a.why_it_fits   AS app_why_it_fits,
                a.created_at    AS app_created_at,
                a.updated_at    AS app_updated_at
            FROM opportunities_fts fts
            JOIN opportunities o ON o.id = fts.opp_id
            LEFT JOIN applications a ON a.opportunity_id = o.id
            WHERE opportunities_fts MATCH ?
            ORDER BY bm25(opportunities_fts)
            LIMIT ?
            """,
            (fts_query, limit),
        )
    except sqlite3.OperationalError:
        # Bad FTS syntax — fall back to empty results rather than crash.
        return []

    results: list[tuple[Opportunity, Application | None]] = []
    for row in cur.fetchall():
        opp = _row_to_opportunity(row)
        app: Application | None = None
        if row["app_id"] is not None:
            app = Application(
                id=row["app_id"],
                opportunity_id=opp.id,
                status=ApplicationStatus(row["app_status"]),
                score=row["app_score"],
                justification=row["app_justification"],
                day_to_day=row["app_day_to_day"],
                why_it_fits=row["app_why_it_fits"],
                created_at=_str_to_datetime(row["app_created_at"]),  # type: ignore[arg-type]
                updated_at=_str_to_datetime(row["app_updated_at"]),  # type: ignore[arg-type]
            )
        results.append((opp, app))
    return results
