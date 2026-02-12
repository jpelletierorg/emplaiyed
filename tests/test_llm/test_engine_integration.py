"""Integration tests for emplaiyed.llm.engine — requires a real API key.

These tests are automatically skipped when OPENROUTER_API_KEY is not set.
They make real (cheap) API calls to verify end-to-end behaviour.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

# Import config FIRST — this triggers .env loading before the skip-check.
from emplaiyed.llm.config import CHEAP_MODEL
from emplaiyed.llm.engine import complete, complete_structured

_has_key = bool(os.environ.get("OPENROUTER_API_KEY"))
skip_no_key = pytest.mark.skipif(
    not _has_key, reason="OPENROUTER_API_KEY not set"
)


class CapitalCity(BaseModel):
    city: str
    country: str


@skip_no_key
class TestIntegrationComplete:
    """Real API calls for ``complete()``."""

    async def test_simple_prompt(self) -> None:
        """A simple prompt should return a non-empty string."""
        result = await complete(
            "Reply with exactly one word: hello.",
            model=CHEAP_MODEL,
        )
        assert isinstance(result, str)
        assert len(result) > 0


@skip_no_key
class TestIntegrationCompleteStructured:
    """Real API calls for ``complete_structured()``."""

    async def test_structured_capital_city(self) -> None:
        """Structured output should return a validated CapitalCity model."""
        result = await complete_structured(
            "What is the capital of France? Respond with the city and country.",
            output_type=CapitalCity,
            model=CHEAP_MODEL,
        )
        assert isinstance(result, CapitalCity)
        assert result.city.lower() == "paris"
        assert "france" in result.country.lower()
