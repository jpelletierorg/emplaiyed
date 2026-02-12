"""Core LLM interface for the emplaiyed toolkit.

Framework choice: **Pydantic AI**
- Native OpenRouter provider (no manual base_url wiring).
- Structured output via Pydantic models with automatic validation & retry.
- Built-in TestModel / FunctionModel for deterministic unit tests without
  real API calls.
- The project already depends on Pydantic, so the mental model is consistent.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from emplaiyed.llm.config import DEFAULT_MODEL, get_api_key

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _build_model(model: str | None = None) -> Model:
    """Create an OpenAI-compatible model backed by OpenRouter."""
    return OpenAIChatModel(
        model or DEFAULT_MODEL,
        provider=OpenRouterProvider(api_key=get_api_key()),
    )


async def complete(
    prompt: str,
    *,
    model: str | None = None,
    _model_override: Model | None = None,
    **kwargs: object,
) -> str:
    """Send a prompt, get a text response.

    Parameters
    ----------
    prompt:
        The user prompt to send to the model.
    model:
        OpenRouter model string (e.g. ``"anthropic/claude-sonnet-4-5"``).
        Falls back to ``DEFAULT_MODEL`` when *None*.
    _model_override:
        Inject a Pydantic-AI ``Model`` instance directly (used by tests to
        supply ``TestModel`` / ``FunctionModel`` without needing an API key).
    **kwargs:
        Passed through to ``Agent.run`` as ``model_settings``.
    """
    llm = _model_override or _build_model(model)
    logger.debug("LLM call (text): model=%s, prompt_len=%d", llm, len(prompt))
    agent: Agent[None, str] = Agent(llm, output_type=str)
    result = await agent.run(prompt)
    return result.output


async def complete_structured(
    prompt: str,
    output_type: type[T],
    *,
    model: str | None = None,
    _model_override: Model | None = None,
    **kwargs: object,
) -> T:
    """Send a prompt, get a validated Pydantic model back.

    Parameters
    ----------
    prompt:
        The user prompt to send to the model.
    output_type:
        A ``pydantic.BaseModel`` subclass describing the expected output.
    model:
        OpenRouter model string. Falls back to ``DEFAULT_MODEL``.
    _model_override:
        Inject a Pydantic-AI ``Model`` instance directly (for tests).
    **kwargs:
        Passed through to ``Agent.run`` as ``model_settings``.
    """
    llm = _model_override or _build_model(model)
    logger.debug("LLM call (structured → %s): model=%s, prompt_len=%d", output_type.__name__, llm, len(prompt))
    agent: Agent[None, T] = Agent(llm, output_type=output_type)
    result = await agent.run(prompt)
    return result.output
