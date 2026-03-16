"""FastAPI dependency injection — database connection, profile, paths."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

from emplaiyed.core.database import get_default_db_path, init_db
from emplaiyed.core.models import Profile
from emplaiyed.core.paths import find_project_root
from emplaiyed.core.profile_store import load_profile, get_default_profile_path


# ---------------------------------------------------------------------------
# Singleton connection (single-user app, one writer at a time)
# ---------------------------------------------------------------------------

_db_conn: sqlite3.Connection | None = None


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a shared SQLite connection.  Initialised on first call.

    Uses ``check_same_thread=False`` because FastAPI serves requests
    in an async thread-pool, but this is safe for a single-user app
    with WAL mode (only one writer at a time).
    """
    global _db_conn
    if _db_conn is None:
        path = get_default_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _db_conn = sqlite3.connect(str(path), check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL;")
        _db_conn.execute("PRAGMA foreign_keys=ON;")
        # Run schema & migrations via init_db-compatible logic
        from emplaiyed.core.database import _SCHEMA, _MIGRATIONS, _POST_MIGRATIONS

        _db_conn.executescript(_SCHEMA)
        for stmt in _MIGRATIONS:
            try:
                _db_conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        for stmt in _POST_MIGRATIONS:
            _db_conn.execute(stmt)
        _db_conn.commit()
    yield _db_conn


def close_db() -> None:
    """Close the shared connection (called at app shutdown)."""
    global _db_conn
    if _db_conn is not None:
        _db_conn.close()
        _db_conn = None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def get_profile() -> Profile | None:
    """Load the current profile, or None if it doesn't exist yet."""
    path = get_default_profile_path()
    if not path.exists():
        return None
    return load_profile(path)


def get_profile_path() -> Path:
    return get_default_profile_path()


# ---------------------------------------------------------------------------
# Asset paths
# ---------------------------------------------------------------------------


def get_assets_dir() -> Path:
    return find_project_root() / "data" / "assets"


def get_data_dir() -> Path:
    return find_project_root() / "data"
