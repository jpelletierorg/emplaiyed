"""Structured output schemas for the apply system.

BrowserApplyState: returned by the Browser Use v3 tool after each step.
ApplyAgentResult: final result from the pydantic_ai apply orchestrator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BrowserApplyState(BaseModel):
    """Structured result from a single Browser Use task step."""

    state: Literal[
        "submitted",
        "needs_email_verification",
        "blocked",
        "failed",
    ] = Field(
        description=(
            "Current state of the application. "
            "'submitted' = application confirmed. "
            "'needs_email_verification' = waiting for email code/link. "
            "'blocked' = cannot proceed (CAPTCHA, unknown field, etc). "
            "'failed' = error occurred."
        )
    )
    confirmation_text: str | None = Field(
        default=None,
        description="Confirmation message if submitted.",
    )
    final_url: str | None = Field(
        default=None,
        description="URL of the page after the action.",
    )
    error_reason: str | None = Field(
        default=None,
        description="Why it could not proceed, if not submitted.",
    )


class ApplyAgentResult(BaseModel):
    """Final result from the pydantic_ai apply orchestrator."""

    submitted: bool
    confirmation_text: str | None = None
    final_url: str | None = None
    error_reason: str | None = None
