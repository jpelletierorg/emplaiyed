"""Telegram notification sender.

Sends formatted briefing messages to the user's Telegram chat
via the Bot API.
"""

from __future__ import annotations

import logging

import httpx

from emplaiyed.inbox.config import TelegramConfig

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


async def send_telegram_message(
    config: TelegramConfig,
    text: str,
    *,
    parse_mode: str = "Markdown",
) -> bool:
    """Send a message via Telegram Bot API.  Returns True on success."""
    url = f"{_API_BASE}/bot{config.bot_token}/sendMessage"
    payload = {
        "chat_id": config.chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    logger.info(
        "Sending Telegram message (chat_id=%s, length=%d chars)",
        config.chat_id,
        len(text),
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                logger.info(
                    "Telegram message sent successfully (msg_id=%s, chat_id=%s)",
                    data["result"]["message_id"],
                    config.chat_id,
                )
                return True
            logger.error(
                "Telegram API rejected message: status=%d description='%s' "
                "chat_id=%s token_prefix=%s...",
                resp.status_code,
                data.get("description", "unknown"),
                config.chat_id,
                config.bot_token[:8] if config.bot_token else "EMPTY",
            )
            return False
    except httpx.TimeoutException:
        logger.error("Telegram API request timed out (15s) — network issue or API down")
        return False
    except httpx.ConnectError as exc:
        logger.error("Cannot connect to Telegram API: %s", exc)
        return False
    except Exception:
        logger.exception("Unexpected error sending Telegram message")
        return False
