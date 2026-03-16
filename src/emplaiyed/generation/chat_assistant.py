"""Chat assistant — ad-hoc text generation with full application context."""

from __future__ import annotations

from pydantic_ai.models import Model

from emplaiyed.llm.engine import complete


def build_system_prompt(
    cv_markdown: str,
    letter_markdown: str,
    job_description: str,
    company: str,
    title: str,
) -> str:
    """Assemble full application context into a system prompt for chat."""
    return "\n".join([
        "You are a helpful assistant for a job applicant.",
        "Your role is to generate paste-ready text: answers to application-form questions,",
        "LinkedIn messages, recruiter emails, etc.",
        "",
        "Rules:",
        "- Be concise and professional.",
        "- Match the language of the existing content below (e.g. if the CV is in French, reply in French).",
        "- Produce text that can be pasted directly — no preamble, no markdown formatting.",
        "",
        f"## Company: {company}",
        f"## Position: {title}",
        "",
        "## Job Description",
        job_description,
        "",
        "## Candidate CV",
        cv_markdown,
        "",
        "## Motivation Letter",
        letter_markdown,
    ])


async def chat(
    query: str,
    *,
    system_prompt: str,
    _model_override: Model | None = None,
) -> str:
    """Send a single query with pre-built context. Each call is independent."""
    return await complete(
        query,
        system_prompt=system_prompt,
        _model_override=_model_override,
    )
