"""Build the natural-language task prompt sent to Browser Use.

Assembles a detailed instruction from the candidate profile, opportunity
details, asset manifest, and autosubmit policy into a single task string
that Browser Use v3 executes autonomously.
"""

from __future__ import annotations

import json
import logging

from emplaiyed.core.models import Opportunity, Profile

logger = logging.getLogger(__name__)


def build_candidate_json(profile: Profile, opportunity: Opportunity) -> str:
    """Serialize the candidate profile and job context into a compact JSON
    string that is embedded directly in the task prompt."""
    data = {
        "candidate": {
            "name": profile.name,
            "email": profile.email,
            "phone": profile.phone,
            "city": profile.address.city if profile.address else None,
            "province_state": profile.address.province_state
            if profile.address
            else None,
            "country": profile.address.country if profile.address else None,
            "linkedin": profile.linkedin,
            "github": profile.github,
        },
        "job": {
            "company": opportunity.company,
            "title": opportunity.title,
            "url": opportunity.source_url,
            "location": opportunity.location,
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_apply_task_prompt(
    profile: Profile,
    opportunity: Opportunity,
    *,
    account_email: str,
) -> str:
    """Build the full task prompt for Browser Use.

    Args:
        profile: Candidate profile.
        opportunity: Target job.
        account_email: The unique email to use if account creation is needed
            (e.g. moi+abc123@jpelletier.org).
    """
    candidate_json = build_candidate_json(profile, opportunity)

    prompt = f"""\
You are applying for a job on behalf of a candidate. Your goal is to submit
the job application autonomously. Here is all the information you need.

## Candidate Information (use this to fill form fields)
```json
{candidate_json}
```

## Files Available In This Session

Two PDF files are uploaded to this session:

- **resume.pdf** — the candidate's tailored resume/CV
- **cover_letter.pdf** — the candidate's tailored cover letter

Upload **resume.pdf** when the site asks for a resume or CV.
Upload **cover_letter.pdf** when the site asks for a cover letter or motivation letter.

## Instructions

1. You are already on the job posting page. Find the "Apply" button or link
   and navigate to the application form. If the apply link redirects to an
   external portal (Greenhouse, Lever, Ashby, Workday, Indeed, etc.), follow
   the redirect.

2. If the portal requires you to create an account or log in, create a new
   account using:
   - Email: {account_email}
   - Password: AutoApply2026!
   - Name: {profile.name}
   If email verification is required (a code or link sent by email), set
   needs_email_verification=true in your output and STOP. Do not guess a
   code. The system will fetch the email for you and resume with the content.

3. Fill in the application form:
   - Use the candidate information JSON above for all identity/contact fields.
   - Upload the correct PDF files as described in the file upload rules above.
   - For "How did you hear about us?" or similar, answer "Job board".
   - SKIP all optional fields. Only fill required fields.
   - If a required field is missing candidate information, enter "N/A".
   - This applies especially to LinkedIn, portfolio, website, and other
     profile-link fields when unavailable.
   - Do NOT stop or report a blocker just because LinkedIn or another
     profile field is missing.
   - Only report a blocker if the site explicitly rejects "N/A" and you
     cannot proceed after trying it.

4. Submit the application.

5. After submission, look for a confirmation message or page. Report what
   you see.

## Important Rules
- Do NOT fabricate work experience, education, or qualifications.
- Do NOT fill optional fields — skip them.
- If you encounter a CAPTCHA, try to solve it. If you cannot, report it.
- If the application requires information not available above and you cannot
  proceed, report the blocker.
- Be efficient: do not browse unnecessarily.
"""
    return prompt


def build_email_verification_prompt(email_content: str) -> str:
    """Build a follow-up prompt that provides fetched email content.

    This is sent to the same Browser Use session after the agent
    reported needs_email_verification=true. The agent should find the
    verification code or link in the email content and continue.
    """
    return f"""\
The system fetched the inbox emails for you. Here they are:

{email_content}

Find the verification code or verification link in these emails and use it
to complete the verification step on the current page. Then continue with
the job application as instructed previously.

If none of these emails contain a relevant verification code or link,
report the issue in your output with error_reason.
"""
