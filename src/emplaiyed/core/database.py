from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Offer,
    OfferStatus,
    Opportunity,
    ScheduledEvent,
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
"""

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
    conn.commit()
    return conn


def get_default_db_path() -> Path:
    """Return ``data/emplaiyed.db`` relative to the project root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent / "data" / "emplaiyed.db"
    return Path(__file__).resolve().parents[3] / "data" / "emplaiyed.db"


# ---------------------------------------------------------------------------
# Opportunity CRUD
# ---------------------------------------------------------------------------


def save_opportunity(conn: sqlite3.Connection, opportunity: Opportunity) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO opportunities
            (id, source, source_url, company, title, description,
             location, salary_min, salary_max, posted_date, scraped_at, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opportunity.id,
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
    conn.commit()


def _row_to_opportunity(row: sqlite3.Row) -> Opportunity:
    return Opportunity(
        id=row["id"],
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


# ---------------------------------------------------------------------------
# Application CRUD
# ---------------------------------------------------------------------------


def save_application(conn: sqlite3.Connection, application: Application) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO applications
            (id, opportunity_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            application.id,
            application.opportunity_id,
            application.status.value,
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
