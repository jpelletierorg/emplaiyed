"""Tests for the LLM-based location filter."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import Address, Aspirations, Opportunity, Profile
from emplaiyed.sources.location_filter import (
    LocationFilterResult,
    LocationVerdict,
    filter_by_location,
)


def _make_profile(**kwargs) -> Profile:
    return Profile(
        name=kwargs.get("name", "Test User"),
        email=kwargs.get("email", "test@example.com"),
        address=kwargs.get(
            "address", Address(city="Longueuil", province_state="Québec")
        ),
        aspirations=kwargs.get(
            "aspirations",
            Aspirations(
                geographic_preferences=[
                    "Montreal",
                    "South Shore of Montreal",
                    "Greater Montreal Area",
                ],
            ),
        ),
    )


def _make_opp(
    title: str = "Dev",
    company: str = "Acme",
    location: str | None = None,
) -> Opportunity:
    return Opportunity(
        source="fake",
        company=company,
        title=title,
        description="A job",
        location=location,
        scraped_at=datetime.now(),
    )


class TestFilterByLocation:
    async def test_no_preferences_returns_all(self):
        """Profile with no geographic preferences returns all opportunities."""
        profile = _make_profile(
            aspirations=Aspirations(geographic_preferences=[]),
        )
        opps = [_make_opp(location="Vancouver, BC") for _ in range(5)]
        result = await filter_by_location(opps, profile)
        assert len(result) == 5

    async def test_none_location_passes_through(self):
        """Opportunities with location=None pass through (benefit of the doubt)."""
        opps = [_make_opp(location=None) for _ in range(3)]
        result = await filter_by_location(opps, _make_profile())
        assert len(result) == 3

    async def test_remote_quick_pass(self):
        """Fully remote opportunities pass without needing an LLM call."""
        opps = [
            _make_opp(title="Dev A", location="Remote"),
            _make_opp(title="Dev B", location="Remote - Canada"),
            _make_opp(title="Dev C", location="Télétravail"),
            _make_opp(title="Dev D", location="Work from home"),
            _make_opp(title="Dev E", location="100% Remote"),
        ]
        # Use TestModel with call_tools=[] (no tools) — if the function
        # tried to call the LLM it would go through, but we verify all pass.
        model = TestModel()
        result = await filter_by_location(opps, _make_profile(), _model_override=model)
        assert len(result) == 5

    async def test_hybrid_remote_does_not_quick_pass(self):
        """'Hybrid - Remote' contains 'hybrid' so it goes to LLM evaluation."""
        opp = _make_opp(title="Dev", company="HybridCo", location="Hybrid - Remote")
        # TestModel will produce a LocationFilterResult with default values;
        # We need to provide custom output that marks index 0 as compatible.
        model = TestModel(
            custom_output_args={
                "verdicts": [
                    {"index": 0, "compatible": True, "reason": "hybrid remote ok"}
                ]
            }
        )
        result = await filter_by_location([opp], _make_profile(), _model_override=model)
        assert len(result) == 1
        assert result[0].company == "HybridCo"

    async def test_llm_rejects_incompatible_location(self):
        """LLM returns compatible=False for Vancouver, True for Montreal."""
        opps = [
            _make_opp(title="Dev Van", company="VanCo", location="Vancouver, BC"),
            _make_opp(title="Dev Mtl", company="MtlCo", location="Montreal, QC"),
        ]
        model = TestModel(
            custom_output_args={
                "verdicts": [
                    {"index": 0, "compatible": False, "reason": "Vancouver is far"},
                    {"index": 1, "compatible": True, "reason": "Montreal matches"},
                ]
            }
        )
        result = await filter_by_location(opps, _make_profile(), _model_override=model)
        assert len(result) == 1
        assert result[0].company == "MtlCo"

    async def test_llm_failure_fails_open(self):
        """If the LLM call raises an exception, all opportunities are kept."""
        opps = [
            _make_opp(title="Dev", company="SomeCo", location="Vancouver, BC"),
            _make_opp(title="Dev2", company="OtherCo", location="Calgary, AB"),
        ]
        # Patch complete_structured to raise an exception
        with patch(
            "emplaiyed.sources.location_filter._evaluate_batch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM is down"),
        ):
            result = await filter_by_location(opps, _make_profile())
        assert len(result) == 2

    async def test_batching(self):
        """25 opportunities are processed in 2 batches (20 + 5)."""
        opps = [
            _make_opp(title=f"Dev {i}", company=f"Co{i}", location=f"City{i}, QC")
            for i in range(25)
        ]
        # Build verdicts for all 25: first batch of 20, second batch of 5
        # TestModel always returns the same output, so we need to handle
        # both batches. The first batch expects indices 0-19, second 0-4.
        # TestModel will return the same custom_output_args each time.
        # We'll use a FunctionModel that returns compatible=True for all
        # indices based on the batch.
        call_count = 0

        def fake_model_fn(messages, info):
            nonlocal call_count
            call_count += 1
            # Return all compatible for whatever batch size
            # We parse the prompt to figure out how many opportunities
            verdicts = []
            for line in str(messages).split("\\n"):
                if line.strip().startswith("[") and "]" in line:
                    try:
                        idx = int(line.strip()[1 : line.strip().index("]")])
                        verdicts.append(
                            {"index": idx, "compatible": True, "reason": "ok"}
                        )
                    except (ValueError, IndexError):
                        pass
            # If we couldn't parse, just return verdicts for 0-24
            if not verdicts:
                verdicts = [
                    {"index": i, "compatible": True, "reason": "ok"} for i in range(20)
                ]
            return info.output_type.model_validate({"verdicts": verdicts})

        model = FunctionModel(fake_model_fn)
        result = await filter_by_location(opps, _make_profile(), _model_override=model)
        assert len(result) == 25
        assert call_count == 2
