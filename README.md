# emplaiyed

AI-powered CLI toolkit that automates your job search pipeline. Build your profile from a CV, scan job boards, score opportunities against your fit, generate tailored CVs and cover letters, track applications through a TUI console, and manage the full lifecycle from outreach to offer acceptance.

## Quick Start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd emplaiyed
cp .env.template .env
# Add your OPENROUTER_API_KEY to .env
uv sync
```

## Workflow

### 1. Build your profile

```bash
emplaiyed profile build          # Interactive — can ingest a PDF CV
emplaiyed profile show           # Review what was extracted
emplaiyed profile enhance        # Enrich highlights with quantified achievements
```

### 2. Scan for opportunities

```bash
emplaiyed sources list           # Show available job sources
emplaiyed sources scan           # Scrape, score, and rank opportunities
```

### 3. Review and act on opportunities

The **console** is the primary interface — a terminal UI for reviewing, applying, and managing applications across pipeline stages:

```bash
emplaiyed console
```

The console organizes applications into tabs: **Queue** (scored, ready to apply), **Applied** (outreach sent, follow-ups), **Active** (interviews), **Offers**, **Closed**, and **Funnel** (stats dashboard). Keyboard-driven: `j`/`k` navigate, `d` marks done, `r` records responses, `f` logs follow-ups, `s` schedules interviews, `o` records offers, and more.

You can also manage applications from the CLI:

```bash
emplaiyed funnel status          # Pipeline stage counts
emplaiyed funnel list            # All applications (filterable by stage)
emplaiyed funnel show <app-id>   # Full detail for one application

emplaiyed work list              # Pending work items
emplaiyed work next              # Show next item to act on
emplaiyed work done <item-id>    # Complete a work item
```

### 4. Interviews and offers

```bash
emplaiyed prep <app-id>          # Generate interview prep cheat sheet
emplaiyed schedule <app-id>      # Schedule an interview event
emplaiyed calendar               # Show upcoming events

emplaiyed offers                 # List pending offers
emplaiyed negotiate <app-id>     # Generate negotiation strategy
emplaiyed accept <app-id>        # Accept and generate acceptance email
```

### 5. Outreach automation

```bash
emplaiyed outreach               # Draft and send outreach for top opportunities
emplaiyed followup               # Check for and send follow-ups
```

## Configuration

Copy `.env.template` to `.env` and set:

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | API key for LLM access via [OpenRouter](https://openrouter.ai) |

SMTP settings for email outreach are collected during `profile build`.

## Architecture

- **Profile**: YAML file (`data/profile.yaml`) — human-readable, editable, fits in LLM context
- **State**: SQLite database (`data/emplaiyed.db`) — applications, interactions, events, transitions
- **Assets**: Generated CVs and cover letters per application (`data/assets/<app-id>/`)
- **LLM**: [Pydantic AI](https://ai.pydantic.dev/) + OpenRouter — structured outputs, model-agnostic
- **Console**: [Textual](https://textual.textualize.io/) TUI with vim-style keybindings
- **CLI**: [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/)

## Development

```bash
uv run pytest                    # Run the full test suite
uv run pytest tests/test_console # Console tests only
uv run emplaiyed --debug ...     # Enable debug logging
emplaiyed reset                  # Wipe database and assets to start fresh
```
