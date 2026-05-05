"""Tests for the orchestrator account email generation."""

from __future__ import annotations

from emplaiyed.apply.orchestrator import _generate_account_email


class TestGenerateAccountEmail:
    def test_basic(self):
        result = _generate_account_email("abc123", "moi@jpelletier.org")
        assert result == "moi+abc123@jpelletier.org"

    def test_different_short_id(self):
        result = _generate_account_email("xyz789", "moi@jpelletier.org")
        assert result == "moi+xyz789@jpelletier.org"

    def test_different_domain(self):
        result = _generate_account_email("test", "user@example.com")
        assert result == "user+test@example.com"
