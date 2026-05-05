"""Tests for the email verification follow-up prompt."""

from __future__ import annotations

from emplaiyed.apply.prompt_builder import build_email_verification_prompt


class TestBuildEmailVerificationPrompt:
    def test_contains_email_content(self):
        email_json = '{"found": true, "emails": [{"subject": "Your code is 123456"}]}'
        prompt = build_email_verification_prompt(email_json)
        assert "123456" in prompt
        assert "verification code" in prompt.lower() or "verification" in prompt.lower()

    def test_contains_instructions(self):
        prompt = build_email_verification_prompt("some email content")
        assert (
            "verification code" in prompt.lower()
            or "verification link" in prompt.lower()
        )
        assert "continue" in prompt.lower()

    def test_not_found_case(self):
        email_json = '{"found": false, "count": 0, "emails": []}'
        prompt = build_email_verification_prompt(email_json)
        assert "found" in prompt
        assert "error_reason" in prompt
