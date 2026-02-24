"""Inbox configuration — loads IMAP and Telegram settings from environment.

All secrets live in ``.env`` (gitignored), never in the YAML profile.
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
class ImapConfig:
    host: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


def get_imap_config() -> ImapConfig:
    """Load IMAP config from environment.  Raises RuntimeError on missing keys."""
    host = os.environ.get("EMPLAIYED_IMAP_HOST", "")
    port = int(os.environ.get("EMPLAIYED_IMAP_PORT", "993"))
    user = os.environ.get("EMPLAIYED_IMAP_USER", "")
    password = os.environ.get("EMPLAIYED_IMAP_PASSWORD", "")

    missing = []
    if not host:
        missing.append("EMPLAIYED_IMAP_HOST")
    if not user:
        missing.append("EMPLAIYED_IMAP_USER")
    if not password:
        missing.append("EMPLAIYED_IMAP_PASSWORD")

    if missing:
        msg = (
            f"IMAP credentials not configured — missing: {', '.join(missing)}. "
            f"Set them in your .env file ({_env_path})."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("IMAP config loaded (host=%s, user=%s, port=%d)", host, user, port)
    return ImapConfig(host=host, port=port, user=user, password=password)


def get_telegram_config() -> TelegramConfig:
    """Load Telegram config from environment.  Raises RuntimeError on missing keys."""
    token = os.environ.get("EMPLAIYED_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("EMPLAIYED_TELEGRAM_CHAT_ID", "")

    missing = []
    if not token:
        missing.append("EMPLAIYED_TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("EMPLAIYED_TELEGRAM_CHAT_ID")

    if missing:
        msg = (
            f"Telegram credentials not configured — missing: {', '.join(missing)}. "
            f"Set them in your .env file ({_env_path})."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info(
        "Telegram config loaded (chat_id=%s, token_prefix=%s...)", chat_id, token[:8]
    )
    return TelegramConfig(bot_token=token, chat_id=chat_id)
