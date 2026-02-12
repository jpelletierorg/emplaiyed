"""Project path resolution — single source of truth for finding the project root."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def find_project_root() -> Path:
    """Walk up from this source file to find the directory containing pyproject.toml."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    # Fallback: assume src/emplaiyed/core/paths.py → 3 levels up
    return Path(__file__).resolve().parents[3]
