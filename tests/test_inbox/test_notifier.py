"""Tests for emplaiyed.inbox.notifier."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emplaiyed.inbox.config import TelegramConfig
from emplaiyed.inbox.notifier import send_telegram_message


@pytest.fixture
def tg_config():
    return TelegramConfig(bot_token="123:ABC", chat_id="456")


async def test_send_message_success(tg_config):
    """Successful Telegram API response returns True."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 1}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("emplaiyed.inbox.notifier.httpx.AsyncClient", return_value=mock_client):
        result = await send_telegram_message(tg_config, "Hello!")

    assert result is True
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    # positional arg is the URL
    assert "bot123:ABC/sendMessage" in call_args[0][0]
    assert call_args[1]["json"]["chat_id"] == "456"
    assert call_args[1]["json"]["text"] == "Hello!"


async def test_send_message_api_error(tg_config):
    """Telegram API returns ok=False returns False."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "Bad Request"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("emplaiyed.inbox.notifier.httpx.AsyncClient", return_value=mock_client):
        result = await send_telegram_message(tg_config, "Hello!")

    assert result is False


async def test_send_message_network_error(tg_config):
    """Network error returns False without raising."""
    mock_client = AsyncMock()
    mock_client.post.side_effect = ConnectionError("refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("emplaiyed.inbox.notifier.httpx.AsyncClient", return_value=mock_client):
        result = await send_telegram_message(tg_config, "Hello!")

    assert result is False
