# Asset Quality Improvement Plan

## Overview
Full implementation plan for improving CV/letter generation quality, adding DOCX output, and creating a Market Gap Advisor feature.

---

## P0 — Quick Wins

### 1.1: Increase letter word limit (config.py)

**File:** `src/emplaiyed/generation/config.py`

Replace the LETTER_SYSTEM_PROMPT Structure + first Rules bullet (lines 104-113):

```python
## Structure (3 paragraphs, 200-300 words total)
Paragraph 1 (2-3 sentences): Hook — identify a specific challenge, goal, or \
initiative at this company (from the job description or industry context) and \
state why solving it drives the candidate. This is NOT generic flattery \
("I admire your innovation") — demonstrate you understand what they NEED.
Paragraph 2 (3-4 sentences): Proof — your 1-2 most relevant accomplishments \
with precise metrics. Concrete examples that make them think "this person \
has done exactly this before." Connect specific technologies or methods to \
the job's requirements when they serve as proof of capability.
Paragraph 3 (1-2 sentences): Close — direct, confident ask for a conversation. \
Mention one specific thing you'd want to discuss or contribute.

## Rules
- TARGET: 200-300 words. Under 200 feels thin. Over 300 is padding.
```

### 1.2: Feed more profile data to letter prompt (letter_generator.py)

**File:** `src/emplaiyed/generation/letter_generator.py`

Replace `_build_letter_prompt` (lines 22-55) with:

```python
def _build_letter_prompt(profile: Profile, opportunity: Opportunity, language: str) -> str:
    """Build the user prompt for letter generation."""
    parts = [
        "Write a motivation letter for this candidate applying to this job.",
        "",
        "## Candidate",
        f"Name: {profile.name}",
    ]

    if profile.skills:
        parts.append(f"Key skills: {format_skills(profile)}")

    if profile.employment_history:
        parts.append(f"Current/recent role: {format_recent_role(profile)}")
        # Calculate approximate years of experience
        from datetime import date
        earliest = min(
            (e.start_date for e in profile.employment_history if e.start_date),
            default=None,
        )
        if earliest:
            years = (date.today() - earliest).days // 365
            parts.append(f"Years of professional experience: {years}")
        # Include top highlights from most recent roles (up to 5 total)
        parts.append("\nKey accomplishments:")
        highlight_count = 0
        for emp in profile.employment_history[:3]:
            for h in emp.highlights[:3]:
                if highlight_count >= 5:
                    break
                parts.append(f"  - ({emp.title} at {emp.company}) {h}")
                highlight_count += 1
            if highlight_count >= 5:
                break

    if profile.education:
        edu = profile.education[0]
        parts.append(f"\nEducation: {edu.degree} in {edu.field}, {edu.institution}")

    if profile.certifications:
        cert_names = [c.name for c in profile.certifications[:3]]
        parts.append(f"Certifications: {', '.join(cert_names)}")

    if profile.aspirations and profile.aspirations.statement:
        parts.append(f"Career goals: {profile.aspirations.statement}")

    parts.extend([
        "",
        "## Target Job",
        f"Company: {opportunity.company}",
        f"Title: {opportunity.title}",
        f"Description: {opportunity.description}",
    ])
    if opportunity.location:
        parts.append(f"Location: {opportunity.location}")

    parts.extend([
        "",
        f"CRITICAL: Write ALL fields (greeting, body, closing) in {language}.",
    ])

    return "\n".join(parts)
```

Need to add `from datetime import date` import at top of file (or inline as shown above).

### 1.4: Relax tech mention ban (config.py)

**File:** `src/emplaiyed/generation/config.py`

Replace line 126:
```
- No technology lists. Only mention tech as proof of capability.
```
With:
```
- Mention specific technologies ONLY when they are named in the job \
description OR when they are central to proving a claim (e.g. "I built a \
RAG pipeline using LangChain that cut support ticket resolution time by \
60%"). Never list technologies for their own sake.
```

### 3.2: Fix PDF ATS bullet (cv.html)

**File:** `src/emplaiyed/rendering/templates/cv.html`

Replace line 138:
```css
    content: "▸";
```
With:
```css
    content: "•";
```

---

## P1 — Structural Improvements

### 1.3: Add aspirations.statement to gap analyzer

**File:** `src/emplaiyed/profile/gap_analyzer.py`

In `_aspiration_field_gaps()`, add after the `work_arrangement` check:

```python
    if not asp.statement:
        gaps.append(
            Gap(
                field_name="aspirations.statement",
                description="Describe your career goals in 1-2 sentences (used in cover letters).",
                priority=GapPriority.REQUIRED,
            )
        )
```

Also add to `_QUESTION_GROUPS` in `builder.py` and `_GROUP_PROMPTS` if using builder pattern.

### 2.3: Add projects field to Profile model

**File:** `src/emplaiyed/core/models.py`

Add new model after `Certification`:

```python
class Project(BaseModel):
    name: str
    description: str
    url: str | None = None  # GitHub link, live demo, etc.
    technologies: list[str] = Field(default_factory=list)
```

Add to `Profile`:
```python
    projects: list[Project] = Field(default_factory=list)
```

### 2.1: Add projects field to GeneratedCV + prompt + templates

**File:** `src/emplaiyed/generation/cv_generator.py`

Add model:
```python
class CVProject(BaseModel):
    name: str
    description: str
    url: str | None = None
    technologies: list[str] = Field(default_factory=list)
```

Add to `GeneratedCV`:
```python
    projects: list[CVProject] = Field(default_factory=list)
```

In `_build_cv_prompt`, add after certifications section:
```python
    if profile.projects:
        parts.append("\n### Projects")
        for proj in profile.projects:
            tech_str = f" [{', '.join(proj.technologies)}]" if proj.technologies else ""
            url_str = f" ({proj.url})" if proj.url else ""
            parts.append(f"- {proj.name}{url_str}{tech_str}: {proj.description}")
```

In `CV_SYSTEM_PROMPT` (config.py), add section:
```
## Projects
If the candidate has projects, include them after Experience. For each project:
- Project name (linked to URL if available)
- 1-2 sentence description of what it does and your contribution
- Technologies used
- Any quantified impact or scale
Projects are especially important for AI/ML roles where hands-on building
is a key differentiator.
```

**File:** `src/emplaiyed/rendering/templates/cv.html`

Add after the experience section (before education):
```html
{% if cv.projects %}
<h2>Projects</h2>
{% for proj in cv.projects %}
<div class="exp-entry">
  <div class="exp-header">
    <div>
      <span class="exp-title">{{ proj.name }}</span>
      {% if proj.url %}<span class="exp-company"> — <a href="{{ proj.url }}" style="color: #2b6cb0; text-decoration: none;">{{ proj.url }}</a></span>{% endif %}
    </div>
  </div>
  <div class="exp-description">{{ proj.description }}</div>
  {% if proj.technologies %}
  <div style="margin-top: 2pt;">
    {% for tech in proj.technologies %}
    <span class="skill-pill">{{ tech }}</span>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endfor %}
{% endif %}
```

**File:** `src/emplaiyed/rendering/markdown_renderer.py`

Add projects section to `render_cv_markdown`:
```python
    if cv.projects:
        lines.append("## Projects\n")
        for proj in cv.projects:
            url_str = f" ({proj.url})" if proj.url else ""
            lines.append(f"### {proj.name}{url_str}\n")
            lines.append(f"{proj.description}\n")
            if proj.technologies:
                lines.append(f"Technologies: {', '.join(proj.technologies)}\n")
            lines.append("")
```

### 3.4: Structured letter body — split into hook/proof/close

**File:** `src/emplaiyed/generation/letter_generator.py`

Replace `GeneratedLetter`:
```python
class GeneratedLetter(BaseModel):
    greeting: str
    hook: str  # Paragraph 1: company's challenge + why it drives you
    proof: str  # Paragraph 2: relevant accomplishments with metrics
    close: str  # Paragraph 3: confident ask + what you'd contribute
    closing: str  # "Sincerely," etc.
    signature_name: str
```

Add a property for backward compat:
```python
    @property
    def body(self) -> str:
        """Combined body text for rendering."""
        return f"{self.hook}\n\n{self.proof}\n\n{self.close}"
```

**File:** `src/emplaiyed/rendering/templates/letter.html`

Replace:
```html
<div class="body">{{ letter.body }}</div>
```
With:
```html
<div class="body">{{ letter.hook }}

{{ letter.proof }}

{{ letter.close }}</div>
```

**File:** `src/emplaiyed/rendering/markdown_renderer.py`

Update `render_letter_markdown`:
```python
def render_letter_markdown(letter: GeneratedLetter) -> str:
    lines = [
        letter.greeting,
        "",
        letter.hook,
        "",
        letter.proof,
        "",
        letter.close,
        "",
        letter.closing,
        "",
        letter.signature_name,
    ]
    return "\n".join(lines)
```

**Note:** The `chat_assistant.py` uses letter markdown which calls `render_letter_markdown`, so it will automatically get the structured output.

---

## P2 — New Capabilities

### 3.1: Add DOCX output

**New dependency:** Add `python-docx>=1.1` to `pyproject.toml` dependencies.

**New file:** `src/emplaiyed/rendering/docx_renderer.py`

```python
"""DOCX rendering — ATS-optimized Word documents for CVs and letters."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from emplaiyed.core.models import Profile
from emplaiyed.generation.cv_generator import GeneratedCV
from emplaiyed.generation.letter_generator import GeneratedLetter


def _add_section_heading(doc: Document, text: str) -> None:
    """Add a section heading in the standard style."""
    heading = doc.add_heading(text, level=2)
    for run in heading.runs:
        run.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)
        run.font.size = Pt(11)


def render_cv_docx(cv: GeneratedCV, path: Path) -> None:
    """Render a GeneratedCV to an ATS-optimized DOCX file."""
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(10)
    font.color.rgb = RGBColor(0x2D, 0x37, 0x48)

    # Name
    name_para = doc.add_heading(cv.name, level=1)
    for run in name_para.runs:
        run.font.size = Pt(18)
        run.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)

    # Professional title
    title_para = doc.add_paragraph(cv.professional_title)
    title_para.style = doc.styles["Normal"]
    for run in title_para.runs:
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)

    # Contact info (single line, pipe-separated)
    contact_parts = [cv.email]
    if cv.phone:
        contact_parts.append(cv.phone)
    if cv.location:
        contact_parts.append(cv.location)
    if cv.linkedin:
        contact_parts.append(cv.linkedin)
    if cv.github:
        contact_parts.append(cv.github)
    contact_para = doc.add_paragraph(" | ".join(contact_parts))
    for run in contact_para.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x71, 0x80, 0x96)

    # Summary
    if cv.summary:
        _add_section_heading(doc, "Summary")
        doc.add_paragraph(cv.summary)

    # Skills
    if cv.skill_categories:
        _add_section_heading(doc, "Skills")
        for cat in cv.skill_categories:
            p = doc.add_paragraph()
            run = p.add_run(f"{cat.category}: ")
            run.bold = True
            run.font.size = Pt(9)
            p.add_run(", ".join(cat.skills)).font.size = Pt(9)

    # Experience
    if cv.experience:
        _add_section_heading(doc, "Experience")
        for exp in cv.experience:
            # Title — Company | Dates
            p = doc.add_paragraph()
            run = p.add_run(f"{exp.title} — {exp.company}")
            run.bold = True
            run.font.size = Pt(10)
            if exp.start_date or exp.end_date:
                dates = f" | {exp.start_date or '?'} – {exp.end_date or 'Present'}"
                date_run = p.add_run(dates)
                date_run.font.size = Pt(9)
                date_run.font.color.rgb = RGBColor(0x71, 0x80, 0x96)
            if exp.description:
                desc_para = doc.add_paragraph(exp.description)
                desc_para.style = doc.styles["Normal"]
                for r in desc_para.runs:
                    r.italic = True
                    r.font.size = Pt(9)
                    r.font.color.rgb = RGBColor(0x71, 0x80, 0x96)
            for h in exp.highlights:
                bp = doc.add_paragraph(h, style="List Bullet")
                for r in bp.runs:
                    r.font.size = Pt(9)

    # Projects
    if cv.projects:
        _add_section_heading(doc, "Projects")
        for proj in cv.projects:
            p = doc.add_paragraph()
            run = p.add_run(proj.name)
            run.bold = True
            run.font.size = Pt(10)
            if proj.url:
                p.add_run(f" — {proj.url}").font.size = Pt(9)
            if proj.description:
                doc.add_paragraph(proj.description).style = doc.styles["Normal"]
            if proj.technologies:
                tech_para = doc.add_paragraph(f"Technologies: {', '.join(proj.technologies)}")
                for r in tech_para.runs:
                    r.font.size = Pt(9)
                    r.font.color.rgb = RGBColor(0x71, 0x80, 0x96)

    # Education
    if cv.education:
        _add_section_heading(doc, "Education")
        for edu in cv.education:
            dates = ""
            if edu.start_date or edu.end_date:
                dates = f" ({edu.start_date or '?'} – {edu.end_date or 'Present'})"
            p = doc.add_paragraph()
            run = p.add_run(f"{edu.degree} in {edu.field}")
            run.bold = True
            run.font.size = Pt(9)
            p.add_run(f" — {edu.institution}{dates}").font.size = Pt(9)

    # Certifications
    if cv.certifications:
        _add_section_heading(doc, "Certifications")
        for cert in cv.certifications:
            date_str = f" ({cert.date})" if cert.date else ""
            p = doc.add_paragraph()
            run = p.add_run(cert.name)
            run.bold = True
            run.font.size = Pt(9)
            p.add_run(f" — {cert.issuer}{date_str}").font.size = Pt(9)

    # Languages
    if cv.languages:
        _add_section_heading(doc, "Languages")
        doc.add_paragraph(" · ".join(cv.languages))

    doc.save(str(path))


def render_letter_docx(
    letter: GeneratedLetter, path: Path, *, profile: Profile | None = None
) -> None:
    """Render a GeneratedLetter to an ATS-optimized DOCX file."""
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    font.color.rgb = RGBColor(0x2D, 0x37, 0x48)

    # Header with candidate info
    if profile:
        name_para = doc.add_heading(profile.name, level=1)
        for run in name_para.runs:
            run.font.size = Pt(16)
            run.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)

        contact_parts = [profile.email]
        if profile.phone:
            contact_parts.append(profile.phone)
        if profile.address and profile.address.city:
            loc = profile.address.city
            if profile.address.province_state:
                loc += f", {profile.address.province_state}"
            contact_parts.append(loc)
        contact_para = doc.add_paragraph(" | ".join(contact_parts))
        for run in contact_para.runs:
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x71, 0x80, 0x96)

        doc.add_paragraph("")  # spacer

    # Greeting
    greeting_para = doc.add_paragraph()
    run = greeting_para.add_run(letter.greeting)
    run.bold = True
    run.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)

    # Body paragraphs
    body_text = letter.body if isinstance(letter.body, str) else f"{letter.hook}\n\n{letter.proof}\n\n{letter.close}"
    for para_text in body_text.split("\n\n"):
        if para_text.strip():
            doc.add_paragraph(para_text.strip())

    # Closing
    doc.add_paragraph(letter.closing)

    # Signature
    sig_para = doc.add_paragraph()
    run = sig_para.add_run(letter.signature_name)
    run.bold = True
    run.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)

    doc.save(str(path))
```

**File:** `src/emplaiyed/generation/pipeline.py`

Add DOCX rendering after PDF rendering in `generate_assets()`:
```python
    from emplaiyed.rendering.docx_renderer import render_cv_docx, render_letter_docx

    # ... existing rendering code ...
    render_cv_docx(cv, paths.cv_docx)
    render_letter_docx(letter_obj, paths.letter_docx, profile=profile)
```

Also need to add `.cv_docx` and `.letter_docx` path properties to the asset paths structure.

### 3.3: Add date + company block to letter template

**File:** `src/emplaiyed/rendering/templates/letter.html`

After the header block and before greeting, add:
```html
{% if today_date %}
<div style="margin-bottom: 14pt; font-size: 9.5pt; color: #718096;">
  {{ today_date }}
</div>
{% endif %}
```

Pass `today_date` from the rendering function using `datetime.now().strftime("%B %d, %Y")`.

### 4.1-4.5: Market Gap Advisor

**New file:** `src/emplaiyed/profile/market_advisor.py`

```python
"""Market Gap Advisor — compares profile against market demand.

Analyzes scored opportunities in the database to identify skills,
experience patterns, and qualifications the candidate should develop
to improve their competitiveness for target roles.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.database import list_applications_by_statuses
from emplaiyed.core.models import ApplicationStatus, Opportunity, Profile
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class SkillGap(BaseModel):
    """A skill that the market demands but the candidate lacks or under-highlights."""
    skill: str
    demand_signal: str = Field(description="How often/strongly this appears in target jobs")
    recommendation: str = Field(description="What the candidate should do about it")
    priority: str = Field(description="high, medium, or low")


class ExperienceGap(BaseModel):
    """An experience pattern the candidate should highlight or develop."""
    area: str
    market_expectation: str
    candidate_status: str = Field(description="What the candidate currently has")
    recommendation: str


class ProjectSuggestion(BaseModel):
    """A project the candidate could build to strengthen their profile."""
    name: str
    description: str
    skills_demonstrated: list[str]
    estimated_effort: str = Field(description="e.g. '1 weekend', '2-4 weeks'")


class CertificationSuggestion(BaseModel):
    """A certification worth pursuing."""
    name: str
    issuer: str
    relevance: str


class ProfileWording(BaseModel):
    """A suggestion to improve how existing experience is presented."""
    current: str
    suggested: str
    reason: str


class MarketGapReport(BaseModel):
    """Full market gap analysis report."""
    summary: str = Field(description="2-3 sentence overall assessment")
    skill_gaps: list[SkillGap] = Field(default_factory=list)
    experience_gaps: list[ExperienceGap] = Field(default_factory=list)
    project_suggestions: list[ProjectSuggestion] = Field(default_factory=list)
    certification_suggestions: list[CertificationSuggestion] = Field(default_factory=list)
    profile_wording: list[ProfileWording] = Field(default_factory=list)
    strengths: list[str] = Field(
        default_factory=list,
        description="Things the candidate already does well relative to market demand",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_ADVISOR_SYSTEM_PROMPT = """\
You are a career strategist specializing in software engineering and applied AI \
roles. You analyze job market signals to give candidates honest, actionable \
advice about gaps between their profile and what employers are actually hiring for.

Be specific and honest. Do NOT pad the report with generic advice like \
"keep learning" or "stay current." Every recommendation must be tied to a \
concrete signal from the job descriptions provided.

If the candidate is already well-positioned, say so. Don't invent gaps.
"""


def _build_advisor_prompt(
    profile: Profile,
    opportunities: list[Opportunity],
) -> str:
    """Build the prompt for market gap analysis."""
    parts = [
        "Analyze the gap between this candidate's profile and what the market demands.",
        "",
        "## Candidate Profile",
        f"Name: {profile.name}",
    ]

    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills)}")

    if profile.employment_history:
        parts.append("\nEmployment:")
        for emp in profile.employment_history:
            start = emp.start_date.isoformat() if emp.start_date else "?"
            end = emp.end_date.isoformat() if emp.end_date else "Present"
            parts.append(f"  {emp.title} at {emp.company} ({start} – {end})")
            for h in emp.highlights:
                parts.append(f"    - {h}")

    if profile.education:
        parts.append("\nEducation:")
        for edu in profile.education:
            parts.append(f"  {edu.degree} in {edu.field}, {edu.institution}")

    if profile.certifications:
        parts.append("\nCertifications:")
        for cert in profile.certifications:
            expiry = ""
            if cert.expiry_date:
                expiry = f" (expired {cert.expiry_date.isoformat()})"
            parts.append(f"  {cert.name} ({cert.issuer}){expiry}")

    if profile.aspirations:
        asp = profile.aspirations
        if asp.target_roles:
            parts.append(f"\nTarget roles: {', '.join(asp.target_roles)}")
        if asp.salary_target:
            parts.append(f"Salary target: ${asp.salary_target:,}")

    parts.append(f"\n## Market Signal: {len(opportunities)} Relevant Job Postings\n")
    for i, opp in enumerate(opportunities[:30]):  # Cap at 30 to stay in context
        desc = opp.description[:400] if opp.description else "No description"
        parts.append(f"[{i+1}] {opp.title} at {opp.company}")
        parts.append(f"    {desc}")
        parts.append("")

    parts.extend([
        "## Instructions",
        "Compare the candidate's profile against the aggregate patterns in these job postings.",
        "Identify:",
        "1. Skills that appear frequently in the jobs but are missing or weak in the profile",
        "2. Experience patterns the market expects that the candidate should develop or highlight",
        "3. Concrete project ideas the candidate could build to fill gaps",
        "4. Certifications worth pursuing (if any)",
        "5. Ways to reword existing experience to better match market language",
        "6. Strengths the candidate already has relative to market demand",
        "",
        "Be brutally honest. The candidate wants to know where they fall short, "
        "not be reassured.",
    ])

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

async def analyze_market_gaps(
    profile: Profile,
    db_conn: sqlite3.Connection,
    *,
    _model_override: Model | None = None,
) -> MarketGapReport:
    """Analyze profile against scored opportunities in the database.

    Pulls opportunities from the database (SCORED and above statuses),
    sends them with the profile to an LLM, and returns a structured
    MarketGapReport with actionable recommendations.
    """
    from emplaiyed.core.database import get_opportunity
    from emplaiyed.llm.config import DEFAULT_MODEL

    # Get all scored+ applications
    statuses = [
        ApplicationStatus.SCORED,
        ApplicationStatus.OUTREACH_PENDING,
        ApplicationStatus.OUTREACH_SENT,
        ApplicationStatus.FOLLOW_UP_PENDING,
        ApplicationStatus.FOLLOW_UP_1,
        ApplicationStatus.FOLLOW_UP_2,
        ApplicationStatus.RESPONSE_RECEIVED,
        ApplicationStatus.INTERVIEW_SCHEDULED,
        ApplicationStatus.INTERVIEW_COMPLETED,
        ApplicationStatus.OFFER_RECEIVED,
    ]
    apps = list_applications_by_statuses(db_conn, statuses)

    if not apps:
        return MarketGapReport(
            summary="No scored opportunities found in the database. "
            "Run a search first with `emplaiyed sources search` to populate market data.",
        )

    # Sort by score descending, take top 50
    apps.sort(key=lambda a: a.score or 0, reverse=True)
    top_apps = apps[:50]

    # Load opportunity details
    opportunities: list[Opportunity] = []
    for app in top_apps:
        opp = get_opportunity(db_conn, app.opportunity_id)
        if opp:
            opportunities.append(opp)

    if not opportunities:
        return MarketGapReport(
            summary="Could not load opportunity details from the database.",
        )

    prompt = _build_advisor_prompt(profile, opportunities)

    return await complete_structured(
        prompt,
        MarketGapReport,
        system_prompt=_ADVISOR_SYSTEM_PROMPT,
        model=DEFAULT_MODEL,
        _model_override=_model_override,
    )
```

**File:** `src/emplaiyed/cli/profile_cmd.py`

Add new command:

```python
@profile_app.command("advisor")
def profile_advisor() -> None:
    """Analyze your profile against market demand and get improvement recommendations."""
    from emplaiyed.core.database import get_default_db_path, init_db
    from emplaiyed.profile.market_advisor import analyze_market_gaps

    path = get_default_profile_path()
    if not path.exists():
        console.print(
            Panel(
                f"No profile found at [bold]{path}[/bold].\n\n"
                "Run [bold green]emplaiyed profile build[/bold green] first.",
                title="No Profile",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    profile = load_profile(path)
    db_path = get_default_db_path()
    if not db_path.exists():
        console.print(
            Panel(
                "No database found. Run a search first:\n"
                "[bold green]emplaiyed sources search[/bold green]",
                title="No Data",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_db(conn)

    console.print("\n[bold cyan]Analyzing your profile against market demand...[/bold cyan]\n")

    try:
        report = asyncio.run(analyze_market_gaps(profile, conn))
    finally:
        conn.close()

    # --- Display report ---

    # Summary
    console.print(Panel(report.summary, title="Market Gap Analysis", border_style="blue"))

    # Strengths
    if report.strengths:
        strength_text = "\n".join(f"  [green]✓[/green] {s}" for s in report.strengths)
        console.print(Panel(strength_text, title="Your Strengths", border_style="green"))

    # Skill gaps
    if report.skill_gaps:
        gap_table = Table(title="Skill Gaps")
        gap_table.add_column("Priority", style="bold")
        gap_table.add_column("Skill", style="cyan")
        gap_table.add_column("Market Signal")
        gap_table.add_column("Recommendation")
        for g in sorted(report.skill_gaps, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.priority, 3)):
            priority_style = {"high": "red", "medium": "yellow", "low": "dim"}.get(g.priority, "")
            gap_table.add_row(
                f"[{priority_style}]{g.priority.upper()}[/{priority_style}]",
                g.skill,
                g.demand_signal,
                g.recommendation,
            )
        console.print(gap_table)

    # Experience gaps
    if report.experience_gaps:
        exp_table = Table(title="Experience Gaps")
        exp_table.add_column("Area", style="cyan")
        exp_table.add_column("Market Expects")
        exp_table.add_column("You Have")
        exp_table.add_column("Action")
        for eg in report.experience_gaps:
            exp_table.add_row(eg.area, eg.market_expectation, eg.candidate_status, eg.recommendation)
        console.print(exp_table)

    # Project suggestions
    if report.project_suggestions:
        console.print("\n[bold]Suggested Projects to Build[/bold]")
        for proj in report.project_suggestions:
            console.print(Panel(
                f"[bold]{proj.name}[/bold]\n"
                f"{proj.description}\n"
                f"[dim]Skills: {', '.join(proj.skills_demonstrated)} | "
                f"Effort: {proj.estimated_effort}[/dim]",
                border_style="cyan",
            ))

    # Certification suggestions
    if report.certification_suggestions:
        cert_table = Table(title="Certifications Worth Pursuing")
        cert_table.add_column("Certification", style="cyan")
        cert_table.add_column("Issuer")
        cert_table.add_column("Relevance")
        for c in report.certification_suggestions:
            cert_table.add_row(c.name, c.issuer, c.relevance)
        console.print(cert_table)

    # Profile wording improvements
    if report.profile_wording:
        console.print("\n[bold]Profile Wording Improvements[/bold]")
        for pw in report.profile_wording:
            console.print(Panel(
                f"[red]Current:[/red] {pw.current}\n"
                f"[green]Suggested:[/green] {pw.suggested}\n"
                f"[dim]Reason: {pw.reason}[/dim]",
                border_style="yellow",
            ))

    console.print("\n[dim]Run [bold]emplaiyed profile enhance[/bold] to improve "
                  "your highlights, or [bold]emplaiyed profile build[/bold] "
                  "to add missing information.[/dim]\n")
```

---

## Test Updates Required

### P0 Tests
- `test_generation/test_letter_generator.py`: Update word count assertions (if any check for 150 limit)
- `test_rendering/test_html_renderer.py`: Update if checking for ▸ character

### P1 Tests
- `test_generation/test_cv_generator.py`: Add tests for projects field in prompt
- `test_generation/test_letter_generator.py`: Update for structured hook/proof/close fields
- `test_rendering/test_markdown_renderer.py`: Update for projects section and structured letter
- `test_rendering/test_html_renderer.py`: Update for projects section in CV template
- `test_profile/test_gap_analyzer.py`: Add test for aspirations.statement gap

### P2 Tests
- New: `test_rendering/test_docx_renderer.py`: Test DOCX rendering for CV and letter
- New: `test_profile/test_market_advisor.py`: Test advisor prompt building and report parsing
- `test_generation/test_pipeline.py`: Update for DOCX output paths

---

## Files Modified Summary

| Phase | File | Change Type |
|-------|------|-------------|
| P0 | `src/emplaiyed/generation/config.py` | Edit (letter prompt) |
| P0 | `src/emplaiyed/generation/letter_generator.py` | Edit (richer prompt) |
| P0 | `src/emplaiyed/rendering/templates/cv.html` | Edit (bullet char) |
| P1 | `src/emplaiyed/core/models.py` | Edit (add Project model) |
| P1 | `src/emplaiyed/generation/cv_generator.py` | Edit (add CVProject + prompt) |
| P1 | `src/emplaiyed/generation/config.py` | Edit (add Projects section) |
| P1 | `src/emplaiyed/generation/letter_generator.py` | Edit (structured body) |
| P1 | `src/emplaiyed/rendering/templates/cv.html` | Edit (projects section) |
| P1 | `src/emplaiyed/rendering/templates/letter.html` | Edit (structured body) |
| P1 | `src/emplaiyed/rendering/markdown_renderer.py` | Edit (projects + letter) |
| P1 | `src/emplaiyed/profile/gap_analyzer.py` | Edit (statement gap) |
| P2 | `pyproject.toml` | Edit (add python-docx dep) |
| P2 | `src/emplaiyed/rendering/docx_renderer.py` | **NEW** |
| P2 | `src/emplaiyed/generation/pipeline.py` | Edit (DOCX rendering) |
| P2 | `src/emplaiyed/rendering/templates/letter.html` | Edit (date block) |
| P2 | `src/emplaiyed/profile/market_advisor.py` | **NEW** |
| P2 | `src/emplaiyed/cli/profile_cmd.py` | Edit (advisor command) |
| P2 | `tests/test_rendering/test_docx_renderer.py` | **NEW** |
| P2 | `tests/test_profile/test_market_advisor.py` | **NEW** |
