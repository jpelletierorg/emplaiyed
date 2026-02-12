"""LLM abstraction layer for emplaiyed."""

from __future__ import annotations

from emplaiyed.llm.engine import complete, complete_structured

__all__ = ["complete", "complete_structured"]
