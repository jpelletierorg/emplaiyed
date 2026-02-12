"""Negotiation advisor — generates counter-offer strategies."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Offer, Opportunity, Profile
from emplaiyed.core.prompt_helpers import format_salary_range
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


class NegotiationStrategy(BaseModel):
    """LLM output for negotiation advice."""

    analysis: str
    recommended_counter: int
    counter_email_subject: str
    counter_email_body: str
    risks: list[str] = Field(default_factory=list)


_NEGOTIATE_PROMPT = """\
You are a salary negotiation expert. Advise on this offer.

CANDIDATE:
- Name: {name}
- Salary minimum: ${salary_min:,}
- Salary target: ${salary_target:,}

OFFER:
- Company: {company}
- Role: {title}
- Offered salary: ${offered:,}

Generate:
1. A 2-sentence analysis of the offer vs expectations
2. A recommended counter-offer amount (realistic, leaves negotiation room)
3. A counter-offer email (subject + body, under 150 words)
4. 1-2 risks to be aware of
"""


async def generate_negotiation(
    profile: Profile,
    opportunity: Opportunity,
    offer: Offer,
    *,
    _model_override: Model | None = None,
) -> NegotiationStrategy:
    """Generate negotiation strategy for an offer."""
    salary_min, salary_target = format_salary_range(profile)

    prompt = _NEGOTIATE_PROMPT.format(
        name=profile.name,
        salary_min=salary_min,
        salary_target=salary_target,
        company=opportunity.company,
        title=opportunity.title,
        offered=offer.salary or 0,
    )

    logger.debug("Generating negotiation strategy for %s", opportunity.company)
    return await complete_structured(
        prompt, output_type=NegotiationStrategy, _model_override=_model_override
    )
