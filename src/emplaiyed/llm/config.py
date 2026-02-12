"""LLM configuration — loads API key and default model from environment.

On import, this module loads the project's ``.env`` file (if present) so that
keys set there are available via ``os.environ``.
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

# Default model: Claude Sonnet 4 on OpenRouter. Fast, capable, cheap.
DEFAULT_MODEL = "anthropic/claude-opus-4.6"

# Cheaper model for integration tests and low-stakes calls.
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
