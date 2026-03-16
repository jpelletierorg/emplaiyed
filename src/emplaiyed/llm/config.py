"""LLM configuration — loads API key and model settings from environment.

On import, this module loads the project's ``.env`` file (if present) so that
keys set there are available via ``os.environ``.

All task-specific models can be overridden via environment variables
(or ``.env``). See ``.env.template`` for the full list.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from the project root.  ``override=False`` means existing env vars win.
from emplaiyed.core.paths import find_project_root as _find_root

_env_path = _find_root() / ".env"
load_dotenv(_env_path, override=False)
logger.debug("Loaded .env from %s (exists=%s)", _env_path, _env_path.exists())

# ---------------------------------------------------------------------------
# Task-specific models — override any of these via .env or env vars.
# ---------------------------------------------------------------------------

DEFAULT_MODEL = os.environ.get(
    "EMPLAIYED_DEFAULT_MODEL", "google/gemini-3-flash-preview"
)

CV_MODEL = os.environ.get("EMPLAIYED_CV_MODEL", "google/gemini-3-flash-preview")
LETTER_MODEL = os.environ.get("EMPLAIYED_LETTER_MODEL", "google/gemini-3-flash-preview")
SEARCH_MODEL = os.environ.get("EMPLAIYED_SEARCH_MODEL", "anthropic/claude-opus-4.6")
SCORING_MODEL = os.environ.get(
    "EMPLAIYED_SCORING_MODEL", "google/gemini-3-flash-preview"
)
LOCATION_FILTER_MODEL = os.environ.get(
    "EMPLAIYED_LOCATION_FILTER_MODEL", "anthropic/claude-haiku-4.5"
)
OUTREACH_MODEL = os.environ.get(
    "EMPLAIYED_OUTREACH_MODEL", "google/gemini-3-flash-preview"
)
PROFILE_MODEL = os.environ.get(
    "EMPLAIYED_PROFILE_MODEL", "google/gemini-3-flash-preview"
)
CONTACT_EXTRACTION_MODEL = os.environ.get(
    "EMPLAIYED_CONTACT_EXTRACTION_MODEL", "anthropic/claude-haiku-4.5"
)
INBOX_MODEL = os.environ.get("EMPLAIYED_INBOX_MODEL", "anthropic/claude-haiku-4.5")

# ---------------------------------------------------------------------------
# Scoring threshold — opportunities scoring below this are marked
# BELOW_THRESHOLD and hidden from the Queue by default.
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = int(os.environ.get("EMPLAIYED_SCORE_THRESHOLD", "30"))

# Cheap model used by integration tests.
CHEAP_MODEL = "anthropic/claude-haiku-4.5"


def get_api_key() -> str:
    """Return the OpenRouter API key from the environment.

    Raises ``RuntimeError`` if the key is not set so callers get a clear
    message instead of a cryptic 401 from the API.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "")
    logger.debug("OPENROUTER_API_KEY present: %s", bool(key))
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. "
            "Add it to your .env file or export it in your shell."
        )
    return key
