# Emplaiyed — Happy Path User Journey

What it looks like to go from "I need a job" to "I accepted an offer" using emplaiyed.

---

## Day 1: Setup & Profile Building

**Component: Profile Builder (D)**

```
$ emplaiyed profile build
```

The agent starts a conversation:

```
Welcome to emplaiyed. I'm going to help you build your job seeker profile.
This profile drives everything — tailored CVs, outreach messaging, scoring.

Do you have an existing CV/resume I can start from? (PDF, DOCX, or paste text)
> /Users/jonathan/Documents/cv.pdf

Parsing your CV...

Here's what I extracted:

  Name:       Jonathan Pelletier
  Email:      jonathan@example.com
  Location:   Quebec City, QC

  Skills:     Python, TypeScript, AWS, Docker, PostgreSQL, Machine Learning

  Employment:
  ┌─────────────┬──────────────────────┬─────────────────┐
  │ Company     │ Role                 │ Period          │
  ├─────────────┼──────────────────────┼─────────────────┤
  │ Acme Corp   │ Senior Developer     │ 2021 - 2024    │
  │ StartupX    │ Full Stack Engineer  │ 2018 - 2021    │
  └─────────────┴──────────────────────┴─────────────────┘

  Education:
  - B.Sc Computer Science, Université Laval (2018)

Anything wrong or outdated here?
> yeah the address changed, I'm at 123 Rue Example now. Also I picked up
> Rust and Go since that CV was written.

Got it — updated address and added Rust and Go to skills.

Now I need a few things your CV doesn't cover:

What kind of role are you looking for?
> Applied AI Engineer, or Senior Backend with ML focus

What's your salary expectation? (minimum you'd accept / target you'd aim for)
> minimum 90k, target 120k

How urgent is your search?
> Very urgent. I need income within the next month.

Open to remote, hybrid, or onsite?
> Remote preferred, hybrid okay if it's in Quebec City

Any industries you're targeting or avoiding?
> Tech, fintech, AI companies. No military/defense.

Profile saved to data/profile.yaml
Run `emplaiyed profile show` to review it anytime.
```

The seeker now has a complete profile. Every downstream component reads from this.

---

## Day 1-2: Source Scanning

**Components: Source Scrapers (E) + Scoring (G)**

The agent already knows what to search for — your profile contains target roles, skills, and location. A simple scan uses your profile to derive the search:

```
$ emplaiyed sources scan

Deriving search from your profile...
  Target roles: Applied AI Engineer, Senior Backend (ML focus)
  Location: Quebec City (expanding to 100km if < 10 results)
  Sources: indeed, linkedin, emploi_quebec

Scanning indeed... 14 found
Scanning linkedin... 18 found
Scanning emploi_quebec... 3 found

Deduplicating... 23 unique opportunities.
Scoring against your profile...

┌───┬────────────────────┬──────────────────────────────┬───────┬──────────────────────────────┐
│ # │ Company            │ Role                         │ Score │ Why                          │
├───┼────────────────────┼──────────────────────────────┼───────┼──────────────────────────────┤
│ 1 │ Coveo              │ Applied ML Engineer          │ 94    │ Perfect stack match, local   │
│ 2 │ Intact             │ Senior AI Developer          │ 87    │ Strong fit, fintech, hybrid  │
│ 3 │ Ubisoft Quebec     │ Backend Engineer - ML        │ 82    │ Good fit, gaming not target  │
│ 4 │ Desjardins         │ Python Developer             │ 71    │ Underleveled title, good pay │
│ 5 │ RandomCorp         │ Junior Data Analyst          │ 23    │ Way below experience level   │
│...│                    │                              │       │                              │
└───┴────────────────────┴──────────────────────────────┴───────┴──────────────────────────────┘

23 opportunities saved. 8 scored above 70.
```

You can also override with explicit parameters or add a specific job:

```
$ emplaiyed sources scan --source indeed --keywords "ML ops" --location "Montreal"
$ emplaiyed sources add --url "https://jobs.coveo.com/senior-ml-engineer" --company "Coveo"
```

**Future vision:** Scanning becomes a background service that runs continuously or on a schedule, with the agent broadening search radius and trying new keyword combinations when results are thin. The seeker just watches the funnel fill up.

All opportunities land in the funnel as DISCOVERED → SCORED.

---

## Day 2-3: Review & Outreach

**Components: State Tracker (J) + Outreach Email (H) + Outreach LinkedIn (I)**

The seeker reviews what's ready:

```
$ emplaiyed funnel status

Application Funnel
┌─────────────────────┬───────┐
│ Stage               │ Count │
├─────────────────────┼───────┤
│ DISCOVERED          │ 15    │
│ SCORED              │ 38    │
│ OUTREACH_SENT       │ 0     │
│ ...                 │       │
│ TOTAL               │ 53    │
└─────────────────────┴───────┘
```

Now they launch outreach for the top-scored opportunities:

```
$ emplaiyed outreach --min-score 75

Found 12 opportunities scored 75+. Preparing outreach...

[1/12] Coveo — Applied ML Engineer (Score: 94)
  Channel: email (hr@coveo.com found on posting)

  Draft email:
  ┌──────────────────────────────────────────────────────────────┐
  │ Subject: Application — Applied ML Engineer                   │
  │                                                              │
  │ Dear Hiring Team,                                            │
  │                                                              │
  │ I'm a Senior Developer with 6 years of experience in Python, │
  │ ML, and cloud infrastructure. At Acme Corp, I led the...     │
  │                                                              │
  │ [Tailored CV attached — emphasizes ML projects and Python]   │
  └──────────────────────────────────────────────────────────────┘

  Attached CV: coveo_applied_ml_engineer_jonathan_pelletier.pdf
  (Tailored: emphasizes ML experience, de-emphasizes frontend work)

  Send this? [Y/n/edit]
> y

  ✓ Sent to hr@coveo.com

[2/12] Intact — Senior AI Developer (Score: 87)
  Channel: linkedin (Easy Apply available)

  Draft cover note:
  ┌──────────────────────────────────────────────────────────────┐
  │ Experienced Python/ML engineer based in Quebec City looking  │
  │ to bring my AI expertise to Intact's data science team...    │
  └──────────────────────────────────────────────────────────────┘

  Apply via LinkedIn Easy Apply? [Y/n/edit]
> y

  ✓ Applied on LinkedIn

...
```

Note: The `[Y/n/edit]` is the **human-in-the-loop gate**. When `APPROVE_OUTREACH=false`, the tool sends automatically.

Each sent application moves from SCORED → OUTREACH_SENT in the funnel.

---

## Day 2-3 (parallel): Cold Research

**Component: Cold Research Agent (F)**

Running in parallel with job board scanning:

```
$ emplaiyed research --mode cold

Based on your profile, I'm researching companies in Quebec City that
might need your skills even if they haven't posted a job...

Researching... (this takes a few minutes)

Found 5 potential targets:

┌───┬──────────────┬────────────────────────────────────────────────────────┐
│ # │ Company      │ Reasoning                                            │
├───┼──────────────┼────────────────────────────────────────────────────────┤
│ 1 │ Absolunet    │ E-commerce firm, recently posted about scaling their  │
│   │              │ recommendation engine. Your ML + Python is a fit.     │
│   │              │ Contact: Marc Dupont (CTO) - LinkedIn                 │
├───┼──────────────┼────────────────────────────────────────────────────────┤
│ 2 │ Beenox       │ Gaming studio, job page mentions "ML for QA". Your   │
│   │              │ backend + ML combo is unusual and valuable here.      │
│   │              │ Contact: careers@beenox.com                           │
├───┼──────────────┼────────────────────────────────────────────────────────┤
│...│              │                                                       │
└───┴──────────────┴────────────────────────────────────────────────────────┘

Draft cold outreach for any of these? Enter numbers (e.g. 1,3) or 'all':
> 1,2

Drafting personalized cold emails...

[Absolunet — Marc Dupont]
  Channel: LinkedIn message
  ┌──────────────────────────────────────────────────────────────┐
  │ Hi Marc — I noticed Absolunet is scaling its recommendation  │
  │ engine. I've spent the last 3 years building ML pipelines    │
  │ in Python at scale and I think I could help accelerate...    │
  └──────────────────────────────────────────────────────────────┘

  Send? [Y/n/edit]
```

These enter the funnel as cold research opportunities with their own tracking.

---

## Day 4-7: The Funnel Moves — Responses Start Coming In

**Components: State Tracker (J) + Follow-up Agent (K)**

The system monitors for responses (email inbox, LinkedIn notifications):

```
$ emplaiyed funnel status

┌─────────────────────┬───────┐
│ Stage               │ Count │
├─────────────────────┼───────┤
│ SCORED              │ 26    │
│ OUTREACH_SENT       │ 10    │
│ RESPONSE_RECEIVED   │ 2     │
│ INTERVIEW_SCHEDULED │ 1     │
│ GHOSTED             │ 3     │
│ TOTAL               │ 53    │
└─────────────────────┴───────┘
```

The follow-up agent runs on a schedule (or manually):

```
$ emplaiyed followup

Checking applications that need follow-up...

3 applications with no response for 5+ days:

[1] Ubisoft Quebec — Backend Engineer - ML
    Sent: 5 days ago via email
    Suggested follow-up:
    ┌──────────────────────────────────────────────────────────────┐
    │ Hi — I wanted to follow up on my application for the        │
    │ Backend Engineer - ML role. I remain very interested in     │
    │ the position and would welcome the chance to discuss how    │
    │ my experience with Python ML pipelines could contribute...  │
    └──────────────────────────────────────────────────────────────┘
    Send follow-up? [Y/n/edit]

[2] Desjardins — Python Developer
    Sent: 7 days ago via LinkedIn Easy Apply
    No direct contact found. Skip? [Y/n]
```

Applications move: OUTREACH_SENT → FOLLOW_UP_1 → FOLLOW_UP_2 → GHOSTED (if no response after all attempts).

When a response comes in (interview scheduled, test assigned, etc.), the seeker logs it:

```
$ emplaiyed schedule a3f8c2d1 --type "phone_screen" --date "2025-01-14 14:00" \
    --notes "With Sarah Chen, Talent Acquisition"

✓ Phone screen scheduled for Jan 14 at 2:00 PM
  Application: Coveo — Applied ML Engineer
  Prep will be available 24h before. Run `emplaiyed prep a3f8c2d1` anytime.
```

View everything coming up:

```
$ emplaiyed calendar

Upcoming Events
┌────────────┬───────┬──────────────────────┬──────────────────────┬──────────────┐
│ Date       │ Time  │ Company              │ Type                 │ Application  │
├────────────┼───────┼──────────────────────┼──────────────────────┼──────────────┤
│ Jan 14     │ 14:00 │ Coveo                │ Phone Screen         │ a3f8c2d1     │
│ Jan 16     │ 10:00 │ Intact               │ Technical Interview  │ b7e2f4a9     │
│ Jan 17     │  —    │ Ubisoft              │ Follow-up due        │ c9d1e3b5     │
└────────────┴───────┴──────────────────────┴──────────────────────┴──────────────┘
```

---

## Day 7-10: Interview Prep

**Component: Prep Agent (L)**

Coveo phone screen is coming up. The seeker finds the application ID from `funnel list`:

```
$ emplaiyed funnel list --stage INTERVIEW_SCHEDULED

┌──────────┬────────────────────┬──────────────────────────────┬─────────────────────┬─────────────┐
│ ID       │ Company            │ Role                         │ Status              │ Updated     │
├──────────┼────────────────────┼──────────────────────────────┼─────────────────────┼─────────────┤
│ a3f8c2d1 │ Coveo              │ Applied ML Engineer          │ INTERVIEW_SCHEDULED │ Jan 12      │
│ b7e2f4a9 │ Intact             │ Senior AI Developer          │ INTERVIEW_SCHEDULED │ Jan 13      │
└──────────┴────────────────────┴──────────────────────────────┴─────────────────────┴─────────────┘
```

Now prep with that ID:

```
$ emplaiyed prep a3f8c2d1

Preparing for: Coveo — Applied ML Engineer
Interview type: Phone Screen (first contact)
Interviewer: Sarah Chen (Talent Acquisition)

Researching Coveo...
  - AI-powered search/recommendations company, Québec City HQ
  - ~1500 employees, public (TSX: CVO)
  - Tech stack: Python, Java, Kubernetes, TensorFlow
  - Recent news: Launched AI-powered commerce search product Q4 2025
  - Glassdoor: 4.1/5, interview difficulty 3.2/5

Cheat Sheet:
┌──────────────────────────────────────────────────────────────────────┐
│ LIKELY QUESTIONS (Phone Screen)                                      │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│ 1. "Tell me about yourself"                                          │
│    → Lead with: 6 years Python/ML, built production pipelines at     │
│      Acme Corp serving 10M+ requests/day. Passionate about applied   │
│      AI — which is why Coveo's search relevance work excites me.     │
│                                                                      │
│ 2. "Why Coveo?"                                                      │
│    → Their AI-powered search is exactly where ML meets real product  │
│      impact. Plus Quebec City — I'm local and committed to the       │
│      community.                                                      │
│                                                                      │
│ 3. "Salary expectations?"                                            │
│    → "I'm targeting the 110-130k range based on my experience and   │
│      the market for ML engineers in Quebec."                         │
│    → DO NOT go below 90k (your hard minimum).                        │
│    → If pressed: "I'm flexible for the right opportunity but want   │
│      to make sure we're in the same range before going further."     │
│                                                                      │
│ 4. "What's your timeline?"                                           │
│    → "I'm actively interviewing and would like to move quickly,     │
│      but Coveo is my top choice so I'm happy to align with your     │
│      process."                                                       │
│    → (Conveys urgency without desperation)                           │
│                                                                      │
│ QUESTIONS TO ASK THEM                                                │
│ • What does the ML team's day-to-day look like?                      │
│ • What's the biggest technical challenge the team is facing?         │
│ • What does the interview process look like from here?               │
│                                                                      │
│ RED FLAGS TO WATCH FOR                                                │
│ • Vague answers about team size or growth plans                      │
│ • "We're looking for someone who wears many hats" (could mean       │
│   understaffed)                                                      │
│ • No clear answer on timeline                                        │
└──────────────────────────────────────────────────────────────────────┘

Save this cheat sheet? [Y/n]
```

---

## Day 10: The Phone Screen (Live Assistance)

**Component: Live Assistant (M)**

```
$ emplaiyed live a3f8c2d1

Starting live assistant for: Coveo — Phone Screen
Listening on system audio...
Dashboard: http://localhost:8420

┌─ LIVE ──────────────────────────────────────────────────────────────┐
│                                                                      │
│ [14:02] Interviewer: "So tell me about your experience with ML       │
│          pipelines in production."                                    │
│                                                                      │
│ SUGGEST: Talk about the Acme Corp recommendation engine.             │
│    You built the feature extraction pipeline processing 10M events/  │
│    day. Mention the A/B testing framework you set up that improved   │
│    model iteration speed by 3x. These map directly to Coveo's       │
│    search relevance work.                                            │
│                                                                      │
│ [14:05] Interviewer: "What monitoring do you put around your         │
│          models?"                                                    │
│                                                                      │
│ SUGGEST: Data drift detection using statistical tests on feature     │
│    distributions. You implemented this at Acme — mention Evidently   │
│    AI integration. Also talk about shadow deployment for new models  │
│    before full rollout. Coveo likely cares about this given their    │
│    search quality SLAs.                                              │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

The seeker sees suggestions in real-time on their screen while they're on the call.

---

## Day 10-14: The Loop

**Components: State Tracker (J) + Prep (L) + Follow-up (K)**

Coveo liked the phone screen — they want a technical interview. The state updates:

```
$ emplaiyed funnel show a3f8c2d1

Coveo — Applied ML Engineer
Status: INTERVIEW_SCHEDULED
Score: 94

Timeline:
  Day 2   Email sent (application)
  Day 8   Response received — phone screen scheduled
  Day 10  Phone screen completed
  Day 10  Response received — technical interview scheduled for Day 15

Next: Technical Interview — Jan 15 at 10am
```

The seeker preps again, this time the agent knows it's round 2:

```
$ emplaiyed prep a3f8c2d1

Preparing for: Coveo — Applied ML Engineer
Interview type: Technical Interview (round 2 of 3)
Previous round: Phone screen on Day 10 — went well

This is a technical round. Expect coding and system design.

Cheat Sheet:
┌──────────────────────────────────────────────────────────────────────┐
│ LIKELY TECHNICAL TOPICS                                              │
│                                                                      │
│ Based on Coveo's stack and the role:                                │
│ • ML system design: "Design a search ranking system"                │
│ • Python coding: Feature engineering, data pipeline code             │
│ • MLOps: Model serving, A/B testing, monitoring                     │
│ • Distributed systems: How to scale inference                       │
│                                                                      │
│ FROM YOUR PHONE SCREEN                                               │
│ Sarah seemed particularly interested in your monitoring work.       │
│ The technical interviewer may dig deeper here.                       │
│                                                                      │
│ SALARY NOTE                                                          │
│ You told Sarah "110-130k range." Don't contradict this.             │
│ If asked again, stay consistent.                                     │
└──────────────────────────────────────────────────────────────────────┘
```

Meanwhile, Intact also responds — they want a first call. The loop runs for multiple companies in parallel.

---

## Day 15-20: Multiple Offers

**Component: Negotiation (N)**

Both Coveo and Intact made offers:

```
$ emplaiyed offers list

┌──────────────┬──────────────────────┬─────────┬────────────┬───────────┐
│ Company      │ Role                 │ Salary  │ Deadline   │ Status    │
├──────────────┼──────────────────────┼─────────┼────────────┼───────────┤
│ Coveo        │ Applied ML Engineer  │ 115,000 │ Jan 25     │ PENDING   │
│ Intact       │ Senior AI Developer  │ 105,000 │ Jan 22     │ PENDING   │
└──────────────┴──────────────────────┴─────────┴────────────┴───────────┘
```

The seeker asks for negotiation help:

```
$ emplaiyed negotiate a3f8c2d1

Current situation:
  • Coveo offered 115k (your target was 120k)
  • Intact offered 105k (deadline in 2 days)
  • Your minimum is 90k — both clear that

Strategy:
┌──────────────────────────────────────────────────────────────────────┐
│ RECOMMENDED PLAY                                                     │
│                                                                      │
│ 1. Secure Intact first. Their deadline is sooner. Tell them you're  │
│    very interested but need until Jan 25 to decide (matches Coveo's │
│    deadline). If they won't extend, consider accepting as safety     │
│    net — you can withdraw later if Coveo comes through higher.      │
│                                                                      │
│ 2. Counter Coveo. You have leverage:                                │
│    - You have a competing offer (Intact)                            │
│    - You're their top candidate (3 rounds, fast process)            │
│    - 115k is below your 120k target                                 │
│                                                                      │
│    Draft counter email:                                              │
│    "Thank you for the offer — I'm very excited about Coveo. I do   │
│    have another competitive offer I'm considering. Given my         │
│    experience and the scope of this role, I was hoping we could     │
│    explore 125k. I'd be ready to sign immediately at that number."  │
│                                                                      │
│ 3. The 125k ask gives room to land at 120k (your real target).     │
│    Asking for exactly your target leaves no negotiation space.       │
│                                                                      │
│ RISK: Don't mention Intact by name. Just "a competing offer."       │
│ RISK: Don't bluff about walking away unless you actually will.      │
└──────────────────────────────────────────────────────────────────────┘

Send the counter email to Coveo? [Y/n/edit]
```

---

## Day 22: Acceptance

**Component: Acceptance (O)**

Coveo came back at 122k. The seeker decides to accept.

```
$ emplaiyed accept a3f8c2d1

Accepting: Coveo — Applied ML Engineer at $122,000/year

Draft acceptance email:
┌──────────────────────────────────────────────────────────────────────┐
│ Dear Sarah,                                                          │
│                                                                      │
│ I'm thrilled to formally accept the offer for the Applied ML        │
│ Engineer position at Coveo at the agreed compensation of $122,000.  │
│                                                                      │
│ I'm looking forward to starting on February 3rd and contributing    │
│ to the team. Please let me know if there's any paperwork or         │
│ onboarding steps I should complete before my start date.            │
│                                                                      │
│ Thank you for the opportunity.                                       │
│                                                                      │
│ Best regards,                                                        │
│ Jonathan Pelletier                                                   │
└──────────────────────────────────────────────────────────────────────┘

Send? [Y/n/edit]
> y

✓ Acceptance sent to sarah.chen@coveo.com

Note: Other active applications are NOT withdrawn automatically.
Companies can and do rescind accepted offers. Your other applications
remain active as a safety net. Use `emplaiyed funnel list` to manage
them manually when you're confident.

Post-acceptance checklist:
  □ Sign formal offer letter when received
  □ Set up direct deposit / banking info
  □ Confirm start date and onboarding schedule
  □ Update LinkedIn profile

Final stats:
  Applications sent:    12
  Responses received:   4
  Interviews completed: 5
  Offers received:      2
  Time to offer:        20 days
  Accepted salary:      $122,000 (above your $120k target)
```

---

## Component Map

| Journey Stage | User Action | Component(s) |
|---|---|---|
| Build profile | `emplaiyed profile build` | Profile Builder (D) |
| Scan job boards | `emplaiyed sources scan` | Source Scrapers (E) + Scoring (G) |
| Paste a specific job | `emplaiyed sources add --url` | Manual Source (E) |
| Find hidden opportunities | `emplaiyed research --mode cold` | Cold Research (F) |
| View pipeline | `emplaiyed funnel status/list/show` | State Tracker (J) + CLI (C) |
| Apply to jobs | `emplaiyed outreach --min-score 75` | Outreach Email (H) / LinkedIn (I) |
| Follow up on silence | `emplaiyed followup` | Follow-up Agent (K) |
| Schedule an event | `emplaiyed schedule <id>` | State Tracker (J) |
| View calendar | `emplaiyed calendar` | State Tracker (J) |
| Prepare for interview | `emplaiyed prep <id>` | Prep Agent (L) |
| Get live help on call | `emplaiyed live <id>` | Live Assistant (M) |
| Compare & negotiate offers | `emplaiyed negotiate <id>` | Negotiation (N) |
| Accept an offer | `emplaiyed accept <id>` | Acceptance (O) |
| Watch it all happen | `http://localhost:8420` | Dashboard (P) |

---

## Automation Progression

All of the `[Y/n/edit]` prompts above are the human-in-the-loop gates. The system is designed so these disappear over time:

| Phase | Human involvement | Config |
|---|---|---|
| Week 1 | Approve every email, every application | `APPROVE_OUTREACH=true` |
| Week 2 | Approve only first contact, auto follow-up | `APPROVE_FOLLOWUP=false` |
| Week 3 | Auto-apply to anything scored 80+, approve rest | `AUTO_APPLY_THRESHOLD=80` |
| Eventually | Full autopilot. Watch the dashboard. Show up to interviews. | All flags off |
