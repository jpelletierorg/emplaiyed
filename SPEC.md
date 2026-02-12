# Emplaiyed — Project Specification

## Vision

A fully autonomous job-seeking pipeline CLI toolkit. Starts with human-in-the-loop at critical decision points, progressively removes the human as model quality and confidence grow. Every component is designed for eventual full automation — toggling off human approval is a config flag, not a rewrite.

## Runtime Environment

- **Execution**: 24/7 Mac Mini (macOS)
- **User**: Single user (Jonathan)
- **LLM Access**: OpenRouter API key ($200 credits) → access to all models
- **Email**: Custom domain + Spacemail (SMTP capable, lands in primary inbox)
- **API Key Storage**: `.env` file at project root

## Technology Decisions

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Best LLM ecosystem (litellm), best scraping tools (playwright), strong CLI libs |
| CLI framework | typer + rich | Type-hinted commands, beautiful terminal output, interactive prompts | 
| LLM abstraction | litellm | Native OpenRouter support, unified interface across all models | why not use pydantic ai for a more agentic framework?? seems like it supports openrouter too and would provide for more of the things we need like an evals framework, some kind of state machine support and other. maybe a bit more research is needed on that front???
| Profile storage | YAML file | Human-readable, editable, fits in LLM context window |
| Schema validation | Pydantic | Enforces profile/job schemas, serializes to/from YAML | alongside pydantic ai that will allow the llm to respond with a pydantic schema....
| State persistence | SQLite | Application tracking, job listings, outreach history |
| Scraping | Playwright | Headless browser, handles JS-rendered job boards | maybe we need to add some kind of browsing agent here too for when headless is just not going to cut it....
| Email | smtplib (stdlib) | Standard SMTP, no extra dependencies |
| Testing | pytest + pytest-asyncio | Standard, well-supported |
| Eval framework | Custom (pytest-based) | LLM output quality assertions, model comparison grid | pydantic ai???? is has built in eval framework.....
| Package manager | uv | Fast, modern Python package management |

## Component Breakdown

### A: `core-data` — Data Models & Persistence

Pydantic models for all domain objects. SQLite database setup. YAML read/write for profile.

**Key schemas:**
- `Profile` — seeker identity, skills, employment history, aspirations, contact info
- `Opportunity` — normalized job listing (source, company, role, description, url, salary range)
- `Application` — state machine instance tying a profile to an opportunity
- `Interaction` — log of every outreach/follow-up/response per application
- `Offer` — formal offer details (salary, benefits, conditions)

**Dependencies:** none

---

### B: `llm-engine` — LLM Abstraction + Eval Framework

Thin wrapper around litellm/OpenRouter. Model registry with cost metadata. Eval framework that:
1. Defines quality assertions per task (scoring, drafting, Q&A generation)
2. Runs candidate models against eval suites
3. Selects cheapest model that passes quality threshold

**Key interfaces:**
- `llm_call(task, prompt, model=None)` — routes to best model for task, falls back to default
- `eval_run(task, models, dataset)` — grid search across models for a task
- `ModelRegistry` — maps tasks to their currently selected model + cost

**Dependencies:** none

---

### C: `cli` — CLI Framework

Top-level `emplaiyed` command with subcommands. Two interaction modes:
- **Command mode**: `emplaiyed profile show`, `emplaiyed funnel status`, `emplaiyed sources scan`
- **Conversational mode**: `emplaiyed chat` — opens interactive agent session for advisory tasks

**Dependencies:** A

---

### D: `profile-builder` — Profile Construction Agent

Conversational agent that builds the seeker profile through:
1. Asks for CV/resume (PDF). Parses it via LLM.
2. Extracts everything it can (name, employment history, skills, education).
3. Presents extraction to user for correction ("the address is no longer valid").
4. Identifies delta between extracted data and full profile schema.
5. Asks targeted questions to fill gaps (date of birth, aspirations, salary expectations, job search urgency, geographic preferences).
6. Writes completed profile to YAML.
7. Supports incremental updates (re-run to update sections).

**CLI**: `emplaiyed profile build` (conversational), `emplaiyed profile show`, `emplaiyed profile edit`

**Dependencies:** A, B, C

---

### E: `source-scrapers` — Job Board Scrapers

Pluggable scraper system. Each source implements a common interface:
```
scrape(query: SearchQuery) → list[RawJobListing]
normalize(raw: RawJobListing) → Opportunity
```

**Initial sources (parallel development):**
- Indeed (browser automation or API)
- LinkedIn (browser automation)
- Emploi Québec (government site, likely more scrapable)
- Manual paste (user pastes URL or job description text)

Jobs are deduplicated by (company, role, source) and persisted to SQLite.

**Dependencies:** A

---

### F: `cold-research` — Spontaneous Candidacy Agent

Deep research agent that:
1. Reads profile (skills, location, aspirations)
2. Identifies local companies in relevant industries
3. Researches each: what they do, tech stack, recent news, likely pain points
4. Scores fit between seeker and company
5. Finds contact person (hiring manager, CTO, etc.) and channel (email, LinkedIn)
6. Drafts cold outreach pitch

Loosely coupled subproject. Can be refined independently.

**Dependencies:** A, B, D

---

### G: `scoring` — Opportunity Scoring

Swappable scoring interface:
```
score(profile: Profile, opportunity: Opportunity) → ScoredOpportunity(score: 0-100, justification: str)
```

**V1 implementation:** Pure LLM — sends profile + job description, asks for structured score + justification.

**Eval:** Curated set of (profile, job) pairs with expected score ranges. Model must agree within tolerance.

**Dependencies:** A, B, D

---

### H: `outreach-email` — Email Channel

1. Takes scored opportunity + profile
2. Drafts personalized application email (cover letter, resume attachment)
3. **Human-in-the-loop gate** (configurable: `APPROVE_OUTREACH=true/false`)
4. Sends via SMTP using seeker's email config from profile
5. Logs interaction to SQLite

Generates tailored CV per opportunity (different emphasis based on job requirements).

**Dependencies:** A, B, G, J

---

### I: `outreach-linkedin` — LinkedIn Channel

Browser automation to:
1. Navigate to job posting or contact profile
2. Apply via LinkedIn Easy Apply or send connection request + message
3. Log interaction

**Dependencies:** A, B, G, J

---

### J: `state-tracker` — Application Lifecycle

State machine per application:

```
DISCOVERED → SCORED → OUTREACH_SENT → FOLLOW_UP_1 → FOLLOW_UP_2 →
  → RESPONSE_RECEIVED → INTERVIEW_SCHEDULED → INTERVIEW_COMPLETED →
  → OFFER_RECEIVED → NEGOTIATING → ACCEPTED / REJECTED / GHOSTED
```

CLI commands:
- `emplaiyed funnel status` — summary counts per stage
- `emplaiyed funnel list [--stage X]` — list applications in a stage
- `emplaiyed funnel show <id>` — full history of one application

**Dependencies:** A, C

---

### K: `follow-up-agent` — Autonomous Follow-ups

Background service/scheduled task that:
1. Scans applications needing follow-up (no response after X days)
2. Loads full context: profile, opportunity, all prior interactions, other active applications
3. Drafts context-aware follow-up (knows about competing offers, interview stages, etc.)
4. Sends via appropriate channel (email, LinkedIn)
5. Configurable: human approval gate or fully autonomous

**Dependencies:** A, B, H, J

---

### L: `prep-agent` — Interview Preparation

Given an upcoming interview (type: screening, technical, behavioral, etc.):
1. Researches company (website, Glassdoor, news)
2. Analyzes job description requirements
3. Cross-references with seeker profile
4. Generates cheat sheet:
   - Likely questions for this interview type
   - Suggested answers tailored to seeker's experience
   - Salary expectation talking points
   - Questions to ask the interviewer
   - Red flags to watch for

**CLI**: `emplaiyed prep <application_id>`

**Dependencies:** A, B, J

---

### M: `live-assistant` — Real-time Call Assistance

Most technically complex component. Subproject with its own detailed spec.

**Capabilities (progressive):**
1. Audio capture from call (system audio or mic)
2. Real-time STT (speech-to-text)
3. LLM processes interviewer questions
4. Websocket dashboard shows live suggestions to seeker
5. (Future) Voice synthesis via ElevenLabs for agent-assisted responses

**Dependencies:** A, B, L

---

### N: `negotiation` — Offer Management & Negotiation

1. Tracks all active offers (salary, benefits, conditions, deadlines)
2. Compares offers side-by-side
3. Suggests negotiation strategy (leverage competing offers, market data)
4. Drafts negotiation emails/messages
5. Human-in-the-loop gate for all employer-facing communication

**CLI**: `emplaiyed offers list`, `emplaiyed offers compare`, `emplaiyed negotiate <application_id>`

**Dependencies:** A, B, J

---

### O: `acceptance` — Acceptance & Closure

1. Drafts acceptance letter based on agreed terms
2. Generates checklist of post-acceptance tasks (resign current job, paperwork, etc.)
3. Marks application as ACCEPTED, closes other active applications
4. Archives the job search

**CLI**: `emplaiyed accept <application_id>`

**Dependencies:** A, B, N

---

### P: `dashboard` — Web Visualization

Lightweight local web UI (probably FastAPI + htmx or similar):
1. Real-time funnel visualization
2. Application cards with status
3. Activity feed (emails sent, responses received, interviews scheduled)
4. (Future) Live call assistant integration

**Dependencies:** A, J

---

## Dependency DAG

```
Level 0 (foundations, parallel):
  [A: core-data]    [B: llm-engine]

Level 1 (needs A):
  [C: cli]          [E: source-scrapers]

Level 2 (needs A+B+C):
  [D: profile-builder]    [J: state-tracker]

Level 3 (needs D or J):
  [F: cold-research]  [G: scoring]  [L: prep-agent]  [N: negotiation]  [P: dashboard]

Level 4 (needs G+J):
  [H: outreach-email]    [I: outreach-linkedin]    [M: live-assistant]

Level 5 (needs H or N):
  [K: follow-up-agent]    [O: acceptance]
```

### Parallelism opportunities at each level:

- **Level 0**: A and B are fully independent → build simultaneously
- **Level 1**: C and E are independent → build simultaneously
- **Level 2**: D and J only share A and C → build simultaneously once Level 1 is done
- **Level 3**: F, G, L, N, P are all independent of each other → up to 5 parallel workstreams
- **Level 4**: H, I, M are independent of each other → 3 parallel workstreams
- **Level 5**: K and O are independent → 2 parallel workstreams

## Development Principles

1. **Everything is tested.** No component is done until tests pass. Prefer automated tests. Use human-in-the-loop testing only as last resort.
2. **Evals for all LLM tasks.** Every LLM-dependent function has an eval suite. Start with best model, grid search for cheaper alternatives.
3. **Human-in-the-loop is a flag.** Every autonomous action has `REQUIRE_APPROVAL` config. Default: `true`. Flip to `false` when confident.
4. **Interfaces over implementations.** Scoring, scraping, outreach channels — all behind swappable interfaces. Change implementations without touching callers.
5. **Parallel development.** Independent components are built by separate agents concurrently. This spec is the contract between them.

## Project Structure

```
emplaiyed/
├── .env                          # OPENROUTER_API_KEY, SMTP creds, etc.
├── pyproject.toml                # uv project config
├── SPEC.md                       # this file
├── src/
│   └── emplaiyed/
│       ├── __init__.py
│       ├── main.py               # typer CLI entrypoint
│       ├── core/                  # A: data models, schemas, db
│       │   ├── models.py
│       │   ├── database.py
│       │   └── profile.py        # YAML profile read/write
│       ├── llm/                   # B: LLM abstraction + evals
│       │   ├── engine.py
│       │   ├── registry.py
│       │   └── evals/
│       ├── cli/                   # C: CLI commands
│       │   ├── profile_cmd.py
│       │   ├── sources_cmd.py
│       │   ├── funnel_cmd.py
│       │   └── chat_cmd.py
│       ├── profile/               # D: profile builder agent
│       │   ├── builder.py
│       │   └── cv_parser.py
│       ├── sources/               # E: job board scrapers
│       │   ├── base.py
│       │   ├── indeed.py
│       │   ├── linkedin.py
│       │   └── emploi_quebec.py
│       ├── research/              # F: cold research agent
│       │   └── agent.py
│       ├── scoring/               # G: opportunity scoring
│       │   ├── scorer.py
│       │   └── evals/
│       ├── outreach/              # H, I: outreach channels
│       │   ├── base.py
│       │   ├── email.py
│       │   ├── linkedin.py
│       │   └── cv_generator.py
│       ├── tracker/               # J: application state machine
│       │   ├── state.py
│       │   └── queries.py
│       ├── followup/              # K: autonomous follow-up agent
│       │   └── agent.py
│       ├── prep/                  # L: interview preparation
│       │   └── agent.py
│       ├── live/                  # M: live call assistant
│       │   ├── audio.py
│       │   ├── stt.py
│       │   └── dashboard.py
│       ├── negotiation/           # N: offer management
│       │   └── advisor.py
│       ├── acceptance/            # O: acceptance manager
│       │   └── manager.py
│       └── dashboard/             # P: web dashboard
│           ├── app.py
│           └── templates/
├── tests/
│   ├── test_core/
│   ├── test_llm/
│   ├── test_profile/
│   ├── test_sources/
│   ├── test_scoring/
│   ├── test_outreach/
│   ├── test_tracker/
│   └── ...
├── evals/                         # LLM eval datasets
│   ├── scoring/
│   ├── drafting/
│   └── profile_extraction/
└── data/                          # runtime data (gitignored)
    ├── profile.yaml
    ├── emplaiyed.db
    └── cvs/
```

## What I Need From You (Jonathan)

1. **OpenRouter API key** → put in `.env` as `OPENROUTER_API_KEY`
2. **Email SMTP credentials** → collected during profile build, stored in profile or `.env`
3. **Your CV in PDF** → provided during `emplaiyed profile build`
4. **Unblock decisions** when agents need human input (API purchases, account setup, etc.)
5. **Approval at human-in-the-loop gates** until we're confident enough to flip the flags
