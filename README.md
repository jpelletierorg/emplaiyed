# emplaiyed

AI-powered CLI that automates your job search: build a profile from your CV, scan job boards, score opportunities, generate tailored CVs and cover letters, and track applications through a terminal UI.

## Setup

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
emplaiyed profile build     # Build your profile from a CV
emplaiyed sources scan      # Scan job boards and score opportunities
emplaiyed console           # Open the TUI to manage your pipeline
```
