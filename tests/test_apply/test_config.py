"""Tests for apply configuration."""

from __future__ import annotations

import os

import pytest

from emplaiyed.apply.config import BrowserUseConfig, get_browser_use_config


class TestBrowserUseConfig:
    def test_defaults(self):
        c = BrowserUseConfig(api_key="test-key")
        assert c.model == "bu-mini"
        assert c.proxy_country_code == "ca"
        assert c.max_cost_usd == 1.50
        assert c.timeout_seconds == 600

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("BROWSER_USE_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="BROWSER_USE_API_KEY"):
            get_browser_use_config()

    def test_loads_from_env(self, monkeypatch):
        monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key-123")
        monkeypatch.setenv("EMPLAIYED_BROWSER_USE_MODEL", "bu-max")
        monkeypatch.setenv("EMPLAIYED_BROWSER_USE_PROXY_COUNTRY_CODE", "us")
        monkeypatch.setenv("EMPLAIYED_BROWSER_USE_MAX_COST_USD", "2.50")
        monkeypatch.setenv("EMPLAIYED_APPLY_TIMEOUT_SECONDS", "600")

        config = get_browser_use_config()
        assert config.api_key == "test-key-123"
        assert config.model == "bu-max"
        assert config.proxy_country_code == "us"
        assert config.max_cost_usd == 2.50
        assert config.timeout_seconds == 600
