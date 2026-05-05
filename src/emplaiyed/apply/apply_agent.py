"""Pydantic AI apply agent — orchestrates browser automation + email tools.

This is the top-level agent that coordinates:
- Browser Use v3 for browser automation (via browser_apply_step tool)
- IMAP inbox reading for email verification (via get_emails tool)

The agent decides when to call each tool and handles the email verification
loop naturally through tool calling, not through hacked outer loops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from browser_use_sdk.v3 import AsyncBrowserUse

from emplaiyed.apply.config import BrowserUseConfig
from emplaiyed.apply.prompt_builder import build_candidate_json
from emplaiyed.apply.providers.browser_use_v3 import BrowserUseSession
from emplaiyed.apply.result_schema import ApplyAgentResult, BrowserApplyState
from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.llm.config import APPLY_AGENT_MODEL, get_api_key

logger = logging.getLogger(__name__)


@dataclass
class ApplyDeps:
    """Dependencies injected into the apply agent's tools."""

    browser_session: BrowserUseSession
    profile: Profile
    opportunity: Opportunity
    account_email: str


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an autonomous job application agent. Your goal is to submit a job
application on behalf of a candidate using the tools available to you.

You have two tools:

1. **browser_apply_step**: Sends a task to a cloud browser that navigates
   websites, fills forms, uploads files, and submits applications. Each call
   continues in the SAME browser session, preserving page state.

2. **get_emails**: Reads today's inbox emails. Use this when the browser
   reports it needs an email verification code or link. The emails will
   contain the code — extract it and pass it back to the browser.

## Strategy

1. Call browser_apply_step with the initial application task.
2. If the browser returns state="needs_email_verification":
   a. Call get_emails to fetch recent emails.
   b. Find the verification code or link in the email content.
   c. Call browser_apply_step again telling the browser to enter the code
      and continue the application.
3. Repeat if needed (up to 3 email attempts).
4. Once the browser returns state="submitted", you are done.
5. If the browser returns state="blocked" or state="failed", report why.

## Rules
- Do NOT fabricate verification codes.
- Do NOT guess — always fetch real emails.
- If the browser encounters a required field with unavailable candidate data,
  use "N/A" instead of blocking.
- Missing LinkedIn, portfolio, or website fields are not blockers by
  themselves.
- Be concise in your browser task descriptions.
"""

def _build_apply_agent() -> Agent[ApplyDeps, ApplyAgentResult]:
    """Build the Pydantic AI agent lazily so imports do not require credentials."""

    agent: Agent[ApplyDeps, ApplyAgentResult] = Agent(
        model=OpenAIChatModel(
            APPLY_AGENT_MODEL,
            provider=OpenRouterProvider(api_key=get_api_key()),
        ),
        output_type=ApplyAgentResult,
        system_prompt=_SYSTEM_PROMPT,
    )

    @agent.tool
    async def browser_apply_step(
        ctx,
        task: str,
    ) -> str:
        """Send a task to the cloud browser.

        The browser session persists across calls, so page state is preserved.
        """
        deps: ApplyDeps = ctx.deps
        result = await deps.browser_session.run_step(task)
        return result.model_dump_json()

    @agent.tool
    async def get_emails(
        ctx,
        waitfor: int = 120,
        max_emails: int = 20,
    ) -> str:
        """Read today's inbox emails when the browser needs verification."""
        from emplaiyed.inbox.agent_tools import get_emails as fetch_emails

        result = await fetch_emails(waitfor=waitfor, max_emails=max_emails)
        return result

    return agent


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_apply_agent(
    config: BrowserUseConfig,
    profile: Profile,
    opportunity: Opportunity,
    *,
    resume_path: Path,
    letter_path: Path,
    account_email: str,
) -> ApplyAgentResult:
    """Run the full apply agent flow.

    Creates a Browser Use session, uploads files, then lets the pydantic_ai
    agent orchestrate browser tasks and email fetching.
    """
    client = AsyncBrowserUse(api_key=config.api_key)
    browser_session = BrowserUseSession(client, config)

    try:
        # 1. Create persistent session
        await browser_session.create()

        # 2. Upload files to session
        await browser_session.upload_files(resume_path, letter_path)

        # 3. Build the initial user prompt
        candidate_json = build_candidate_json(profile, opportunity)
        user_prompt = f"""\
Apply for this job:

**Company**: {opportunity.company}
**Title**: {opportunity.title}
**URL**: {opportunity.source_url}

## Candidate Information
```json
{candidate_json}
```

## Files in the browser session
- resume.pdf — upload when asked for resume/CV
- cover_letter.pdf — upload when asked for cover letter

## Account creation (if needed)
- Email: {account_email}
- Password: AutoApply2026!
- Name: {profile.name}

## Rules
- Fill only required fields, skip optional ones.
- Do not fabricate work experience or qualifications.

Start the application now using the browser_apply_step tool.
"""

        # 4. Build deps and run the agent
        deps = ApplyDeps(
            browser_session=browser_session,
            profile=profile,
            opportunity=opportunity,
            account_email=account_email,
        )

        logger.info(
            "Starting apply agent for %s (%s) at %s",
            opportunity.company,
            opportunity.title,
            opportunity.source_url,
        )

        apply_agent = _build_apply_agent()
        result = await apply_agent.run(user_prompt, deps=deps)
        output = result.output

        logger.info(
            "Apply agent finished: submitted=%s, confirmation=%s",
            output.submitted,
            output.confirmation_text,
        )

        return output

    except Exception:
        logger.exception("Apply agent failed")
        raise
    finally:
        await browser_session.cleanup()
        await client.close()
