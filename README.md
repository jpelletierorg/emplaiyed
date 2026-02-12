# emplaiyed

AI-powered CLI toolkit that automates your job search. It builds your profile, finds opportunities, applies on your behalf, prepares you for interviews, and helps you negotiate offers — with as little manual effort as possible.

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd emplaiyed
cp .env.template .env
# Add your OPENROUTER_API_KEY to .env
uv sync
```

## Usage

```bash
# Show available commands
emplaiyed --help

# Build your profile (interactive, can ingest your CV)
emplaiyed profile build

# Show your profile
emplaiyed profile show

# Scan job sources
emplaiyed sources scan

# View your application funnel
emplaiyed funnel status
emplaiyed funnel list --stage INTERVIEW_SCHEDULED
emplaiyed funnel show <application_id>

# Prepare for an upcoming interview
emplaiyed prep <application_id>

# Manage offers
emplaiyed offers list
emplaiyed offers compare
emplaiyed negotiate <application_id>

# Accept an offer
emplaiyed accept <application_id>
```

## Configuration

Copy `.env.template` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | API key for LLM access via OpenRouter |
| `SMTP_HOST` | Later | Email server hostname (collected during profile build) |
| `SMTP_PORT` | Later | Email server port |
| `SMTP_USER` | Later | Email login |
| `SMTP_PASSWORD` | Later | Email password |
