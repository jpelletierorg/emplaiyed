"""Interview prep agent — generates cheat sheets for upcoming interviews."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.core.prompt_helpers import format_recent_role, format_salary_range, format_skills
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


class PrepSheet(BaseModel):
    """LLM output for an interview prep cheat sheet."""

    company_summary: str
    likely_questions: list[str] = Field(default_factory=list)
    suggested_answers: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    salary_notes: str
    red_flags: list[str] = Field(default_factory=list)


_PREP_PROMPT = """\
You are an interview preparation coach. Generate a concise cheat sheet
for the following interview.

CANDIDATE:
- Name: {name}
- Key skills: {skills}
- Recent role: {recent_role}
- Salary range: min ${salary_min:,}, target ${salary_target:,}

OPPORTUNITY:
- Company: {company}
- Title: {title}
- Location: {location}
- Description (first 1500 chars):
{description}

Generate:
1. A 2-sentence company summary
2. 3-4 likely interview questions
3. Suggested answer talking points (matching the candidate's experience)
4. 3 questions the candidate should ask
5. Salary negotiation notes based on the candidate's range
6. 1-2 red flags to watch for
"""


async def generate_prep(
    profile: Profile,
    opportunity: Opportunity,
    *,
    _model_override: Model | None = None,
) -> PrepSheet:
    """Generate an interview prep sheet."""
    salary_min, salary_target = format_salary_range(profile)

    prompt = _PREP_PROMPT.format(
        name=profile.name,
        skills=format_skills(profile),
        recent_role=format_recent_role(profile),
        salary_min=salary_min,
        salary_target=salary_target,
        company=opportunity.company,
        title=opportunity.title,
        location=opportunity.location or "Not specified",
        description=(opportunity.description[:1500] if opportunity.description else "No description"),
    )

    logger.debug("Generating prep for %s at %s", opportunity.title, opportunity.company)
    return await complete_structured(
        prompt, output_type=PrepSheet, _model_override=_model_override
    )
