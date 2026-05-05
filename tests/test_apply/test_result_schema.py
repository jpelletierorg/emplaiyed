"""Tests for the apply result schemas."""

from __future__ import annotations

from emplaiyed.apply.result_schema import ApplyAgentResult, BrowserApplyState


class TestBrowserApplyState:
    def test_submitted(self):
        s = BrowserApplyState(
            state="submitted",
            confirmation_text="Thank you for applying!",
            final_url="https://example.com/confirm",
        )
        assert s.state == "submitted"

    def test_needs_email(self):
        s = BrowserApplyState(
            state="needs_email_verification",
            error_reason="Waiting for verification code",
        )
        assert s.state == "needs_email_verification"

    def test_blocked(self):
        s = BrowserApplyState(
            state="blocked",
            error_reason="CAPTCHA required",
        )
        assert s.state == "blocked"

    def test_failed(self):
        s = BrowserApplyState(
            state="failed",
            error_reason="Browser crash",
        )
        assert s.state == "failed"

    def test_json_schema(self):
        schema = BrowserApplyState.model_json_schema()
        assert "state" in schema["properties"]
        assert "confirmation_text" in schema["properties"]


class TestApplyAgentResult:
    def test_submitted(self):
        r = ApplyAgentResult(submitted=True, confirmation_text="Done!")
        assert r.submitted is True

    def test_not_submitted(self):
        r = ApplyAgentResult(submitted=False, error_reason="Blocked")
        assert r.submitted is False
        assert r.error_reason == "Blocked"
