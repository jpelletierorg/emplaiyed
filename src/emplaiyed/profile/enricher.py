"""Interactive profile enricher — rewrites duty-focused highlights into
achievement-focused bullets using follow-up questions and LLM assistance.

Uses the same I/O protocol (PromptFunc / PrintFunc) as the profile builder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Profile
from emplaiyed.core.profile_store import (
    get_default_profile_path,
    load_profile,
    save_profile,
)
from emplaiyed.llm.engine import complete_structured
from emplaiyed.profile.quality_analyzer import HighlightQuality, analyze_highlight_quality


class PromptFunc(Protocol):
    def __call__(self, message: str) -> str: ...


class PrintFunc(Protocol):
    def __call__(self, message: str) -> None: ...


# ---------------------------------------------------------------------------
# LLM-assisted highlight rewriting
# ---------------------------------------------------------------------------

class RewrittenHighlights(BaseModel):
    highlights: list[str] = Field(description="Rewritten highlights in CAR format")


_REWRITE_PROMPT = """\
You are an expert resume writer. Rewrite the following employment highlights \
using CAR format (Challenge-Action-Result). Incorporate the additional context \
provided by the user to add quantified outcomes and concrete achievements.

Role: {title} at {company}

Current highlights:
{highlights}

Additional context from the user:
"{user_context}"

Rules:
- Start each bullet with a strong action verb
- Include quantified outcomes (percentages, dollar amounts, team sizes, etc.) \
where the user's context provides them
- Keep each bullet concise (1-2 lines)
- Do NOT fabricate metrics — only use what the user provided
- Return the same number of highlights or fewer if some are redundant
"""


async def _rewrite_highlights(
    company: str,
    title: str,
    highlights: list[str],
    user_context: str,
    *,
    _model_override: Model | None = None,
) -> list[str]:
    """Use LLM to rewrite highlights incorporating user-provided context."""
    highlights_text = "\n".join(f"- {h}" for h in highlights)
    prompt = _REWRITE_PROMPT.format(
        title=title,
        company=company,
        highlights=highlights_text,
        user_context=user_context,
    )
    from emplaiyed.llm.config import PROFILE_MODEL

    result = await complete_structured(
        prompt,
        output_type=RewrittenHighlights,
        model=PROFILE_MODEL,
        _model_override=_model_override,
    )
    return result.highlights


# ---------------------------------------------------------------------------
# Main enricher
# ---------------------------------------------------------------------------

async def enrich_profile(
    *,
    prompt_fn: PromptFunc,
    print_fn: PrintFunc,
    profile_path: Path | None = None,
    _model_override: Model | None = None,
) -> Profile:
    """Run the interactive profile enricher.

    Analyzes employment highlights for quality, asks follow-up questions
    for weak (duty-focused) highlights, and rewrites them with LLM assistance.
    """
    path = profile_path or get_default_profile_path()

    if not path.exists():
        print_fn(
            f"No profile found at {path}. "
            "Run `emplaiyed profile build` first."
        )
        raise FileNotFoundError(f"No profile at {path}")

    profile = load_profile(path)
    quality_report = analyze_highlight_quality(profile)

    # Filter to roles that have weak highlights
    roles_to_enrich = [hq for hq in quality_report if hq.weak_highlights]

    if not roles_to_enrich:
        print_fn(
            "Your profile highlights look good — no duty-focused bullets detected."
        )
        return profile

    print_fn(
        f"Found {len(roles_to_enrich)} role(s) with highlights that could be "
        "stronger. Let's add some concrete achievements.\n"
    )

    for hq in roles_to_enrich:
        emp = profile.employment_history[hq.employment_index]
        weak_texts = [emp.highlights[i] for i in hq.weak_highlights]

        print_fn(f"\n--- {emp.title} at {emp.company} ---")
        print_fn("These highlights are duty-focused and could use metrics:")
        for text in weak_texts:
            print_fn(f"  - {text}")

        answer = prompt_fn(
            f"For your role at {emp.company}, can you quantify any outcomes? "
            "For example: team size, cost savings, performance improvements, "
            "users served, uptime percentages?"
        )

        if answer.strip().lower() in ("skip", "none", "no", ""):
            print_fn("Skipping this role.")
            continue

        # Rewrite all highlights for this role (not just weak ones) to
        # maintain consistency, but pass the user context for enrichment
        rewritten = await _rewrite_highlights(
            company=emp.company,
            title=emp.title,
            highlights=emp.highlights,
            user_context=answer,
            _model_override=_model_override,
        )

        print_fn("\nRewritten highlights:")
        for h in rewritten:
            print_fn(f"  - {h}")

        approval = prompt_fn("Accept these changes? (yes/no)")
        if approval.strip().lower() in ("yes", "y", ""):
            profile.employment_history[hq.employment_index].highlights = rewritten
            print_fn("Updated!")
        else:
            print_fn("Kept original highlights.")

    save_profile(profile, path)
    print_fn(f"\nProfile saved to {path}")
    return profile
