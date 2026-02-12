from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from emplaiyed.core.models import Profile

logger = logging.getLogger(__name__)


def _serialize_value(obj: Any) -> Any:
    """Recursively convert Pydantic-dumped dicts so dates become ISO strings
    and None values are preserved naturally for YAML."""
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_value(item) for item in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def load_profile(path: Path) -> Profile:
    """Read a YAML file and return a validated Profile."""
    logger.debug("Loading profile from %s", path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Profile file is empty: {path}")
    return Profile.model_validate(data)


def save_profile(profile: Profile, path: Path) -> None:
    """Serialize a Profile to human-readable YAML and write it to *path*."""
    logger.debug("Saving profile to %s", path)
    data = profile.model_dump(mode="python", exclude_none=True)
    data = _serialize_value(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def get_default_profile_path() -> Path:
    """Return ``data/profile.yaml`` relative to the project root.

    The project root is determined by walking up from this source file until
    we find the directory that contains ``pyproject.toml``.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent / "data" / "profile.yaml"
    # Fallback: two levels up from src/emplaiyed/core/
    return Path(__file__).resolve().parents[3] / "data" / "profile.yaml"
