"""Browser Use configuration — loads API keys and settings from environment.

All secrets live in ``.env`` (gitignored), never in the YAML profile.
Follows the same pattern as ``emplaiyed.inbox.config``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from emplaiyed.core.paths import find_project_root

logger = logging.getLogger(__name__)

_env_path = find_project_root() / ".env"
load_dotenv(_env_path, override=False)


@dataclass(frozen=True)
class BrowserUseConfig:
    api_key: str
    model: str = "bu-mini"
    proxy_country_code: str = "ca"
    max_cost_usd: float = 1.50
    timeout_seconds: int = 600


def get_browser_use_config() -> BrowserUseConfig:
    """Load Browser Use config from environment.  Raises RuntimeError on missing keys."""
    api_key = os.environ.get("BROWSER_USE_API_KEY", "")

    if not api_key:
        msg = (
            "BROWSER_USE_API_KEY not configured. "
            f"Set it in your .env file ({_env_path})."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    model = os.environ.get("EMPLAIYED_BROWSER_USE_MODEL", "bu-mini")
    proxy = os.environ.get("EMPLAIYED_BROWSER_USE_PROXY_COUNTRY_CODE", "ca")
    max_cost = float(os.environ.get("EMPLAIYED_BROWSER_USE_MAX_COST_USD", "1.50"))
    timeout = int(os.environ.get("EMPLAIYED_APPLY_TIMEOUT_SECONDS", "300"))

    logger.info(
        "Browser Use config loaded (model=%s, proxy=%s, max_cost=$%.2f)",
        model,
        proxy,
        max_cost,
    )
    return BrowserUseConfig(
        api_key=api_key,
        model=model,
        proxy_country_code=proxy,
        max_cost_usd=max_cost,
        timeout_seconds=timeout,
    )
