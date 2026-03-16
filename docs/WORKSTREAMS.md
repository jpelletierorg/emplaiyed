# Workstreams: Making Emplaiyed Production-Ready

**Last updated:** 2026-02-16
**Research:** See `docs/research/w1_*.md` through `w6_*.md` for full findings.

---

## Status Overview

| # | Workstream | Status | Key Decision Needed |
|---|-----------|--------|---------------------|
| W1 | Agentic job search | Research done | None — clear approach |
| W2 | More sources | Research done | Register Jooble API key |
| W3 | Asset quality | Research done | DOCX output priority |
| W4 | Contact extraction | Blocked on W2 | — |
| W5 | Multi-language | Blocked on W3 | — |
| W6 | Email monitoring | Research done | IMAP provider choice |

---

## Phase 2 Implementation Plan

Based on research findings, here is the implementation order with dependencies.

### Wave 1: Quick wins (no dependencies, high impact)

**W3a — Prompt improvements** (~30 min)
Apply the 6 HIGH-priority prompt changes from w3 research:
1. Add explicit job title matching instruction to CV prompt
2. Replace vague ATS keyword instruction with 5-step extraction process
3. Increase cover letter word count from 150 to 200-300
4. Add pain-point angle to cover letter hook paragraph
5. Add anti-AI-detection guidance to both prompts
6. Lean toward 2 pages for 8+ year candidates

Files: `src/emplaiyed/generation/config.py`
Tests: Update existing generation tests for new word counts/structure.

**W2a — Jooble source** (~2 hours)
Free REST API, JSON in/out, no HTML parsing. Best ROI of any source.
- Register at https://jooble.org/api/about
- Add `JOOBLE_API_KEY` to `.env.template`
- Implement `JoobleSource(BaseSource)` in `src/emplaiyed/sources/jooble.py`
- Map Jooble response fields to `Opportunity` model
- Tests with recorded API responses

Files: `src/emplaiyed/sources/jooble.py`, `tests/test_sources/test_jooble.py`

### Wave 2: Core features (depend on Wave 1)

**W1 — Agentic search agent** (~3 hours)
Single Pydantic AI agent with one `search_jobs` tool. Agent reasons about profile, generates diverse queries, adapts based on results.
- Model: `anthropic/claude-haiku-4.5` (cheap, fast, sufficient for query strategy)
- ~165 lines in `src/emplaiyed/sources/search_agent.py`
- Tool returns summaries (not full descriptions) to keep context small
- Dedup in tool, not agent. Scoring post-agent, not inline.
- `UsageLimits(request_limit=15, tool_calls_limit=20)` as guardrail
- Expected: ~7 tool calls, ~18 unique opportunities, ~$0.03, ~45 seconds per run

Files: `src/emplaiyed/sources/search_agent.py`, `tests/test_sources/test_search_agent.py`
Depends on: W2a (Jooble source gives the agent a second source to work with)

**W2b — Jobillico source** (~3 hours)
Quebec-focused, high relevance for Montreal. Clean URL structure suggests server-side rendering.
- First: verify httpx+BS4 feasibility (fetch search URL, check if results are in HTML)
- URL pattern: `https://www.jobillico.com/search-jobs/{keyword-slug}/montreal/quebec`
- If JS-rendered: fall back to Playwright (adds ~3 more hours)

Files: `src/emplaiyed/sources/jobillico.py`, `tests/test_sources/test_jobillico.py`

**W5 — Multi-language generation** (~2 hours)
Quebec market requires French assets for French postings (Bill 96).
- Detect job posting language (heuristic: check for common French words in description)
- Add `language: str = "en"` parameter to `generate_cv()` and `generate_letter()`
- Language directive in prompt: "Generate all content in {language}."
- Languages section always prominent in output

Files: `src/emplaiyed/generation/cv_generator.py`, `src/emplaiyed/generation/letter_generator.py`, `src/emplaiyed/generation/config.py`
Depends on: W3a (prompt improvements should land first)

### Wave 3: Advanced features (depend on Wave 2)

**W4 — Contact extraction** (~2 hours)
Extract recruiter/contact info from job postings for outreach.
- LLM-based extraction: name, email, phone, title from job description
- `ContactInfo` Pydantic model stored in `Opportunity.raw_data` or a new field
- Hook into scraping pipeline: extract contacts after fetching full posting

Files: `src/emplaiyed/sources/contact_extractor.py`
Depends on: W2 sources (more postings = more contacts to extract)

**W2c — Talent.com source** (~3 hours)
Montreal-founded aggregator, good Canadian coverage, some overlap with Jooble.
- URL pattern: `https://ca.talent.com/jobs/k-{keyword}-l-montreal-qc`
- Verify server-side rendering feasibility

Files: `src/emplaiyed/sources/talent.py`, `tests/test_sources/test_talent.py`

**W3b — DOCX output** (~3 hours)
DOCX is the safest ATS format. Add as primary submission format alongside PDF.
- `python-docx` dependency
- Single-column, standard headings, standard bullets, Calibri 10-11pt
- Contact info in document body (not headers/footers)
- ATS validation test: render → extract text → verify sections present

Files: `src/emplaiyed/generation/docx_renderer.py`, tests
New dependency: `python-docx`

**W6 — Email monitoring** (~6 hours)
Poll mailbox for recruitment responses, classify, match to applications.
- `imapclient>=3.0` + stdlib `email` + `html2text`
- App Passwords for MVP (no OAuth2 setup needed)
- Matching cascade: thread ID → sender domain → LLM fallback
- `processed_emails` SQLite table for deduplication
- LLM classification: ~$0.0018/email with Haiku
- CLI: `emplaiyed inbox check`, `emplaiyed inbox setup`

Files: `src/emplaiyed/inbox/` (new package), `src/emplaiyed/cli/inbox_cmd.py`
New dependencies: `imapclient>=3.0`, `html2text>=2024.2`

---

## Key Architectural Decisions

### Sources covered after full implementation
| Source | Type | Method |
|--------|------|--------|
| Job Bank Canada | Government | httpx + BS4 (existing) |
| Jooble | Aggregator (hundreds of sources) | REST API (JSON) |
| Jobillico | Quebec-focused | httpx + BS4 |
| Talent.com | Canadian aggregator | httpx + BS4 |

**Skipped:** Indeed (Cloudflare), LinkedIn (anti-bot), Glassdoor (login wall), Wellfound (anti-scraping). All partially covered through Jooble aggregation.

### Search agent model
`anthropic/claude-haiku-4.5` — query strategy reasoning is not complex enough to justify Sonnet. ~$0.03 per search run.

### Email auth
App Passwords for MVP. OAuth2 (Gmail via `google-auth-oauthlib`, Outlook via `msal`) deferred to later. Auth layer is isolated so swapping is easy.

### Asset formats
- **PDF** (WeasyPrint): human-readable, polished version
- **DOCX** (python-docx): ATS-optimized submission format (new)
- Language matched to job posting language (French/English)

---

## Cost Summary (per typical weekly usage)

| Activity | Frequency | Cost |
|----------|-----------|------|
| Agentic search | 3 runs/week | ~$0.09 |
| Opportunity scoring | 50 opps/week | ~$0.12 |
| CV generation | 10 CVs/week | ~$0.30 |
| Letter generation | 10 letters/week | ~$0.05 |
| Email classification | 100 emails/week | ~$0.18 |
| **Total** | | **~$0.74/week** |
