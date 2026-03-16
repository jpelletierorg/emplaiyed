"""Tests for emplaiyed.inbox.config."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from emplaiyed.inbox.config import (
    ImapConfig,
    TelegramConfig,
    get_imap_config,
    get_telegram_config,
)


# ---------------------------------------------------------------------------
# ImapConfig
# ---------------------------------------------------------------------------


class TestGetImapConfig:
    def test_loads_from_env(self):
        env = {
            "EMPLAIYED_IMAP_HOST": "mail.example.com",
            "EMPLAIYED_IMAP_PORT": "993",
            "EMPLAIYED_IMAP_USER": "user@example.com",
            "EMPLAIYED_IMAP_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = get_imap_config()
        assert cfg.host == "mail.example.com"
        assert cfg.port == 993
        assert cfg.user == "user@example.com"
        assert cfg.password == "secret"

    def test_default_port(self):
        env = {
            "EMPLAIYED_IMAP_HOST": "mail.example.com",
            "EMPLAIYED_IMAP_USER": "user@example.com",
            "EMPLAIYED_IMAP_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = get_imap_config()
        assert cfg.port == 993

    def test_raises_on_missing_host(self):
        env = {
            "EMPLAIYED_IMAP_HOST": "",
            "EMPLAIYED_IMAP_USER": "user@example.com",
            "EMPLAIYED_IMAP_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="IMAP credentials"):
                get_imap_config()

    def test_raises_on_missing_user(self):
        env = {
            "EMPLAIYED_IMAP_HOST": "mail.example.com",
            "EMPLAIYED_IMAP_USER": "",
            "EMPLAIYED_IMAP_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="IMAP credentials"):
                get_imap_config()

    def test_raises_on_missing_password(self):
        env = {
            "EMPLAIYED_IMAP_HOST": "mail.example.com",
            "EMPLAIYED_IMAP_USER": "user@example.com",
            "EMPLAIYED_IMAP_PASSWORD": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="IMAP credentials"):
                get_imap_config()


# ---------------------------------------------------------------------------
# TelegramConfig
# ---------------------------------------------------------------------------


class TestGetTelegramConfig:
    def test_loads_from_env(self):
        env = {
            "EMPLAIYED_TELEGRAM_BOT_TOKEN": "123:ABC",
            "EMPLAIYED_TELEGRAM_CHAT_ID": "456",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = get_telegram_config()
        assert cfg.bot_token == "123:ABC"
        assert cfg.chat_id == "456"

    def test_raises_on_missing_token(self):
        env = {
            "EMPLAIYED_TELEGRAM_BOT_TOKEN": "",
            "EMPLAIYED_TELEGRAM_CHAT_ID": "456",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="Telegram credentials"):
                get_telegram_config()

    def test_raises_on_missing_chat_id(self):
        env = {
            "EMPLAIYED_TELEGRAM_BOT_TOKEN": "123:ABC",
            "EMPLAIYED_TELEGRAM_CHAT_ID": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(RuntimeError, match="Telegram credentials"):
                get_telegram_config()
