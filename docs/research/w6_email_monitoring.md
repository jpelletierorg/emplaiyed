# Week 6 Research: Email Monitoring for Emplaiyed

**Date:** 2026-02-16
**Goal:** Design an email monitoring feature that polls a mailbox for recruitment responses, matches them to existing applications, and creates work items.

---

## 1. Python IMAP Libraries

### 1.1 `imaplib` (stdlib)

**Version:** Ships with Python 3.12+
**Maintenance:** Always maintained (part of CPython)

| Aspect | Assessment |
|--------|-----------|
| API ergonomics | Low-level, verbose. Returns `(status, [data])` tuples. You write raw IMAP commands. |
| Async support | None. Blocking I/O only. |
| OAuth2 support | Yes, via `IMAP4_SSL.authenticate('XOAUTH2', callback)`. |
| Parsing | Returns raw bytes; you do all MIME parsing yourself. |

**Verdict:** Usable but painful. Every operation requires manual byte-wrangling. The OAuth2 support is there but crude (you construct the SASL string yourself).

```python
import imaplib

conn = imaplib.IMAP4_SSL("imap.gmail.com")
auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
conn.authenticate("XOAUTH2", lambda x: auth_string.encode())
conn.select("INBOX")
status, data = conn.search(None, "UNSEEN")
```

### 1.2 `IMAPClient` (third-party)

**Version:** 3.0.1 (July 2024), docs reference 3.1.0
**PyPI:** https://pypi.org/project/IMAPClient/
**Maintenance:** Low activity in the last 12 months. Supports Python 3.8-3.14. Functional but development has slowed.

| Aspect | Assessment |
|--------|-----------|
| API ergonomics | Excellent. Pythonic API, returns parsed Python objects. Best DX of all options. |
| Async support | None. Synchronous only. |
| OAuth2 support | Yes. Built-in `oauthbearer_login()` and XOAUTH2 support. Tested against Gmail, Office365, Yahoo. |
| Extras | IMAP IDLE support, folder management, flag manipulation, UID-based operations. |

**Verdict:** Best API for synchronous use. The lack of async is the only real drawback. Since our polling runs as a CLI command (not a long-lived server), sync is fine.

```python
from imapclient import IMAPClient

client = IMAPClient("imap.gmail.com", ssl=True)
client.oauthbearer_login(email, access_token)
# or: client.authenticate("XOAUTH2", lambda x: auth_string)

client.select_folder("INBOX")
uids = client.search(["UNSEEN"])
for uid, data in client.fetch(uids, ["RFC822"]).items():
    raw_email = data[b"RFC822"]
```

### 1.3 `aioimaplib` (async)

**Version:** 2.0.1 (January 2025)
**PyPI:** https://pypi.org/project/aioimaplib/
**Maintenance:** Active, single maintainer. Major version bump (1.x -> 2.x) in Jan 2025.

| Aspect | Assessment |
|--------|-----------|
| API ergonomics | Lower-level than IMAPClient. Mimics imaplib's API style but with async/await. |
| Async support | Full asyncio. Native coroutines for all IMAP operations. |
| OAuth2 support | Yes, via `authenticate("XOAUTH2", authobject_callback)`. Tested with Outlook. |
| Extras | RFC2177 IDLE support (async push notifications for new mail). |

**Verdict:** The only real option if you need async IMAP. API is rougher than IMAPClient but workable. The IDLE support is interesting for future real-time monitoring, but overkill for our MVP.

```python
import aioimaplib

client = aioimaplib.IMAP4_SSL(host="imap.gmail.com")
await client.wait_hello_from_server()
auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
await client.authenticate("XOAUTH2", lambda x: auth_string)
await client.select("INBOX")
response = await client.search("UNSEEN")
```

### 1.4 Recommendation

**Use `IMAPClient` for the MVP.** Reasons:

1. Our email check is a CLI command (`emplaiyed inbox check`), not a long-lived async server. We already use `asyncio.run()` for LLM calls; IMAP polling can be synchronous without blocking anything.
2. IMAPClient has the best API by far -- parsed responses, Pythonic flag handling, built-in OAuth2 methods.
3. The project already uses `asyncio` for LLM calls (via pydantic-ai), but wrapping a synchronous IMAP call in `asyncio.to_thread()` is trivial if we ever need it.
4. If we later want real-time push (IDLE), we can add `aioimaplib` as a separate daemon. That's a phase 2 concern.

**Dependency to add:** `imapclient>=3.0`

---

## 2. Email Parsing

### 2.1 Options

| Library | Version | Notes |
|---------|---------|-------|
| `email` (stdlib) | Python 3.12+ | Full MIME parser. `email.message_from_bytes()` + `walk()` to iterate parts. Handles multipart/alternative, multipart/mixed, etc. |
| `mail-parser` | 4.1.4 (June 2025) | Wraps stdlib `email`. Returns a clean object with `.text_plain`, `.text_html`, `.attachments`, `.subject`, `.from_`, etc. Apache 2 license. |
| `html2text` | Latest April 2025 | Converts HTML to readable plaintext/Markdown. Great for HTML-only emails. |
| `beautifulsoup4` | Already a dependency | Can extract text from HTML via `.get_text()`. We already have this. |

### 2.2 Parsing Strategy

Recruitment emails come in three flavors:

1. **Plain text** -- Easy. Just read `text/plain` part.
2. **Multipart with both text and HTML** -- Prefer `text/plain` part.
3. **HTML-only** -- Must convert to text. Common with automated recruiter emails from ATS systems (Lever, Greenhouse, Workday).

**Recommended approach: `email` stdlib + `html2text`.**

`mail-parser` is nice but adds a dependency for what amounts to 20 lines of code. The stdlib `email` module handles MIME parsing perfectly well; the only gap is HTML-to-text conversion, which `html2text` fills cleanly.

```python
import email
from email.policy import default as default_policy
import html2text

def extract_email_text(raw_bytes: bytes) -> str:
    """Extract readable text from a raw email message."""
    msg = email.message_from_bytes(raw_bytes, policy=default_policy)

    # Try plain text first
    body = msg.get_body(preferencelist=("plain",))
    if body:
        return body.get_content()

    # Fall back to HTML → text conversion
    body = msg.get_body(preferencelist=("html",))
    if body:
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        return h.handle(body.get_content())

    return ""


def extract_email_metadata(raw_bytes: bytes) -> dict:
    """Extract headers and metadata from a raw email."""
    msg = email.message_from_bytes(raw_bytes, policy=default_policy)
    return {
        "from": msg["From"],
        "to": msg["To"],
        "subject": msg["Subject"],
        "date": msg["Date"],
        "message_id": msg["Message-ID"],
        "in_reply_to": msg.get("In-Reply-To"),
        "references": msg.get("References"),
    }
```

**Dependencies to add:** `html2text>=2024.2`

### 2.3 Handling Email Threads

Email threads are identified by the `References` and `In-Reply-To` headers (RFC 2822). When we send an outreach email, we should store the `Message-ID` in the interaction metadata. Then, when checking incoming mail, we match `In-Reply-To` or `References` headers against stored Message-IDs.

This is the most reliable matching signal -- more reliable than subject line or sender domain matching.

---

## 3. Matching Emails to Applications

This is the core design challenge. An incoming email needs to be linked to the correct `Application` in our database.

### 3.1 Matching Strategies (in priority order)

**Strategy 1: Thread ID matching (highest confidence)**
- When we record an `EMAIL_SENT` interaction, store the outgoing `Message-ID` in `interaction.metadata`.
- When an email arrives with an `In-Reply-To` or `References` header that contains one of our stored Message-IDs, it's a direct reply.
- Confidence: ~100%. This is how email clients track threads.

**Strategy 2: Sender domain matching**
- Extract the domain from the sender's email address.
- Match against `opportunity.company` in the database (fuzzy match).
- Example: email from `recruiter@acme.com` matches an application where `company = "Acme Corp"`.
- Confidence: ~80%. Fails when recruiters use personal email, staffing agencies, or when you have multiple applications at the same company.

**Strategy 3: Subject line matching**
- Match the email subject against stored opportunity titles or outreach subjects.
- Example: subject contains "Senior Python Developer" which matches an opportunity title.
- Confidence: ~60%. Subject lines get mangled, abbreviated, or changed by recruiters.

**Strategy 4: LLM-based matching (fallback)**
- Send the email content + a list of active applications to the LLM.
- Ask it to identify which application the email relates to.
- Confidence: ~90% but costs money and adds latency.

### 3.2 Recommended Matching Pipeline

```
Incoming email
    │
    ├─── Check In-Reply-To / References headers
    │    against stored Message-IDs
    │    → Match found? Done. (Strategy 1)
    │
    ├─── Extract sender domain, fuzzy-match
    │    against active application companies
    │    → Single match? Done. (Strategy 2)
    │
    ├─── If multiple domain matches or no match,
    │    use LLM to classify
    │    → Match found? Done. (Strategy 4)
    │
    └─── No match → Flag as "unmatched recruitment email"
         for manual review
```

### 3.3 Data Model Changes

To support thread matching, we need to store outgoing Message-IDs. The `Interaction.metadata` dict already supports this:

```python
# When recording an outreach email:
interaction = Interaction(
    application_id=app_id,
    type=InteractionType.EMAIL_SENT,
    direction="outbound",
    channel="email",
    content=f"Subject: {subject}\n\n{body}",
    metadata={
        "message_id": "<unique-id@emplaiyed.local>",
        "subject": subject,
        "to": recipient_email,
    },
    created_at=datetime.now(),
)
```

We also need a new table to track processed emails (deduplication):

```sql
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id  TEXT PRIMARY KEY,
    mailbox     TEXT NOT NULL,
    folder      TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    matched_application_id TEXT,
    classification TEXT,  -- "recruitment", "rejection", "interview", "spam", etc.
    FOREIGN KEY (matched_application_id) REFERENCES applications(id)
);
```

---

## 4. OAuth2 for Gmail and Outlook

### 4.1 Gmail OAuth2

**Requirement:** As of September 30, 2024, Google killed "Less Secure Apps" and basic password auth for all accounts. You must use either OAuth2 or App Passwords (with 2FA enabled).

**Option A: App Passwords (simpler, recommended for MVP)**

If the user has 2FA enabled on their Google account, they can generate an App Password at https://myaccount.google.com/apppasswords. This gives them a 16-character password that works with standard IMAP login -- no OAuth2 flow needed.

```python
client = IMAPClient("imap.gmail.com", ssl=True)
client.login("user@gmail.com", "xxxx-xxxx-xxxx-xxxx")  # App Password
```

Pros: Dead simple. No OAuth2 setup, no token refresh, no Google Cloud Console project.
Cons: Requires the user to manually create the app password. Less secure (static credential). Google could deprecate this path in the future.

**Option B: Full OAuth2 (production-grade)**

Setup steps:
1. Create a project in Google Cloud Console.
2. Enable the Gmail API (or just use IMAP scope directly).
3. Create OAuth2 credentials (Desktop application type).
4. Download `client_secret.json`.
5. First run: user goes through browser consent flow, we get a refresh token.
6. Subsequent runs: use refresh token to get fresh access tokens.

Libraries needed: `google-auth-oauthlib`, `google-auth`

```python
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
from pathlib import Path

SCOPES = ["https://mail.google.com/"]
TOKEN_PATH = Path("data/gmail_token.pickle")
CREDS_PATH = Path("data/client_secret.json")

def get_gmail_credentials():
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return creds

# Usage with IMAPClient:
creds = get_gmail_credentials()
client = IMAPClient("imap.gmail.com", ssl=True)
client.oauthbearer_login(email, creds.token)
```

### 4.2 Outlook/Microsoft 365 OAuth2

**Requirement:** Microsoft 365 requires OAuth2 for all IMAP connections. No app password fallback for organizational accounts (personal Outlook.com accounts may still support app passwords).

Libraries needed: `msal` (Microsoft Authentication Library)

```python
import msal

CLIENT_ID = "your-app-registration-client-id"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["https://outlook.office365.com/.default"]

def get_outlook_credentials():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)

    # Try cache first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]

    # Interactive flow (first time)
    flow = app.initiate_device_flow(scopes=SCOPES)
    print(flow["message"])  # "Go to https://microsoft.com/devicelogin and enter code XXXXXX"
    result = app.acquire_token_by_device_flow(flow)
    return result["access_token"]

# Usage with IMAPClient:
token = get_outlook_credentials()
auth_string = f"user={email}\x01auth=Bearer {token}\x01\x01"
client = IMAPClient("outlook.office365.com", ssl=True)
client.authenticate("XOAUTH2", lambda x: auth_string)
```

### 4.3 Recommendation for MVP

**Start with App Passwords (Gmail) / basic IMAP auth.** Here's why:

1. OAuth2 requires registering an app with Google/Microsoft, which adds friction and setup time.
2. For a personal-use CLI tool, App Passwords are perfectly fine.
3. The IMAP connection code is identical either way -- only the auth step differs.
4. We can add OAuth2 as a configuration option later without changing the monitoring logic.

**Config model addition:**

```python
class ImapConfig(BaseModel):
    host: str           # "imap.gmail.com"
    port: int = 993
    user: str           # "user@gmail.com"
    password: str | None = None     # App password
    auth_method: str = "password"   # "password" | "oauth2_gmail" | "oauth2_outlook"
    oauth2_client_id: str | None = None
    oauth2_token_path: str | None = None
```

Store this in the profile YAML alongside the existing `smtp_config`, or in `.env` for credentials.

---

## 5. Polling Architecture

### 5.1 CLI Command vs. Background Daemon

| Approach | Pros | Cons |
|----------|------|------|
| **CLI command** (`emplaiyed inbox check`) | Simple, no daemon management, runs in user's terminal, easy to test | Must be run manually or via cron |
| **Background daemon** | Real-time monitoring, IDLE push support | Complex: PID files, logging, crash recovery, resource usage |
| **Cron / launchd** | System-managed scheduling, reliable | Platform-specific setup, harder to debug |

**Recommendation: CLI command + optional cron/launchd.**

For a personal CLI tool, a daemon is overengineered. The user runs `emplaiyed inbox check` manually or sets up a cron job:

```bash
# Check every 15 minutes
*/15 * * * * cd /path/to/project && emplaiyed inbox check >> /tmp/emplaiyed-inbox.log 2>&1
```

Or on macOS, a launchd plist for automatic scheduling.

### 5.2 Polling Frequency

- **Every 15 minutes** is the sweet spot for a job search tool. Recruitment emails don't need sub-minute response times.
- Gmail rate limits IMAP connections to ~15,000/day, so even 1-minute polling wouldn't hit limits.
- Each check should be fast: connect, search UNSEEN, fetch new messages, disconnect. Under 5 seconds typically.

### 5.3 Deduplication: Tracking Processed Emails

Two complementary strategies:

**Strategy A: IMAP flags (server-side)**
- After processing an email, mark it with a custom IMAP flag (e.g., `\\Flagged` or a custom keyword like `emplaiyed-processed`).
- On next poll, search for `UNSEEN` or `NOT KEYWORD emplaiyed-processed`.
- Pros: Works across machines. State lives on the mail server.
- Cons: Custom keywords not supported by all IMAP servers. Gmail treats flags oddly.

**Strategy B: Local state (database)**
- Store each processed email's `Message-ID` in the `processed_emails` table.
- On each poll, fetch UNSEEN emails, check if their Message-ID is already in the table, skip if so.
- Pros: Reliable, works with any IMAP server, gives us an audit log.
- Cons: State is local to this machine.

**Recommendation: Use both.** Mark as SEEN on the server (so the user's regular email client also sees them as read), and track Message-IDs locally for deduplication. The `processed_emails` table serves as the authoritative record.

### 5.4 Processing Pipeline

```
emplaiyed inbox check
    │
    ├── 1. Connect to IMAP (using ImapConfig)
    ├── 2. Search INBOX for UNSEEN messages
    ├── 3. Fetch each message
    │
    ├── 4. For each message:
    │   ├── Check if Message-ID is in processed_emails → skip if yes
    │   ├── Extract text and metadata
    │   ├── Classify: is this recruitment-related? (LLM)
    │   │   ├── No  → record as processed, skip
    │   │   └── Yes → continue
    │   ├── Match to application (thread ID → domain → LLM)
    │   ├── Extract structured data (LLM): interview date, contact, next steps
    │   ├── Record Interaction (EMAIL_RECEIVED)
    │   ├── Create WorkItem (REVIEW_RESPONSE)
    │   ├── Transition application status if appropriate
    │   └── Record in processed_emails
    │
    └── 5. Disconnect, print summary
```

---

## 6. LLM-Based Email Classification

### 6.1 Classification Task

Given an email, we need to determine:
1. **Is it recruitment-related?** (filter out newsletters, ads, unrelated mail)
2. **What type?** (response to application, interview invite, rejection, offer, generic acknowledgment)
3. **What structured data can we extract?** (interview date/time, contact name, next steps)
4. **What's the urgency?** (interview tomorrow vs. "we'll be in touch")

### 6.2 Pydantic AI Agent Design

This fits perfectly with the existing `complete_structured` pattern:

```python
from pydantic import BaseModel, Field
from enum import Enum

class EmailCategory(str, Enum):
    NOT_RECRUITMENT = "NOT_RECRUITMENT"
    APPLICATION_ACKNOWLEDGMENT = "APPLICATION_ACKNOWLEDGMENT"
    INTERVIEW_INVITATION = "INTERVIEW_INVITATION"
    RESPONSE_POSITIVE = "RESPONSE_POSITIVE"
    RESPONSE_NEGATIVE = "RESPONSE_NEGATIVE"      # rejection
    OFFER = "OFFER"
    FOLLOW_UP_REQUEST = "FOLLOW_UP_REQUEST"       # they want more info from us
    GENERIC_RECRUITER = "GENERIC_RECRUITER"        # unsolicited recruiter outreach

class EmailClassification(BaseModel):
    """Structured extraction from an incoming email."""
    is_recruitment: bool = Field(
        description="Whether this email is related to a job application or recruitment"
    )
    category: EmailCategory
    company_name: str | None = Field(
        default=None,
        description="The company name mentioned in the email"
    )
    contact_name: str | None = Field(
        default=None,
        description="Name of the person who sent or is referenced in the email"
    )
    contact_title: str | None = Field(
        default=None,
        description="Job title of the contact person (e.g., 'Recruiter', 'Hiring Manager')"
    )
    job_title_mentioned: str | None = Field(
        default=None,
        description="The job title/role mentioned in the email"
    )
    interview_date: str | None = Field(
        default=None,
        description="Proposed interview date/time, if any (ISO 8601 format)"
    )
    next_steps: str | None = Field(
        default=None,
        description="What the candidate is expected to do next"
    )
    urgency: str = Field(
        default="normal",
        description="'urgent' if action needed within 24h, 'normal' otherwise"
    )
    summary: str = Field(
        description="One-sentence summary of the email's purpose"
    )


_CLASSIFY_PROMPT = """\
Analyze this email received during a job search. Classify it and extract
structured information.

If the email is NOT related to job searching/recruitment (e.g., it's a
newsletter, promotion, personal message, etc.), set is_recruitment=false
and category=NOT_RECRUITMENT. Leave other fields as null.

EMAIL METADATA:
From: {from_addr}
Subject: {subject}
Date: {date}

EMAIL BODY:
{body}

ACTIVE APPLICATIONS (for context):
{applications_context}
"""
```

### 6.3 Cost Estimation

Using Claude Haiku 4.5 on OpenRouter ($1.00/M input, $5.00/M output):

| Component | Tokens (est.) | Cost |
|-----------|---------------|------|
| System prompt + classification prompt | ~300 input | $0.0003 |
| Email body (average recruitment email) | ~500 input | $0.0005 |
| Active applications context | ~200 input | $0.0002 |
| Structured output | ~150 output | $0.00075 |
| **Total per email** | **~1,150** | **~$0.0018** |

At 20 emails/day checked: **~$0.036/day**, **~$1.08/month**.

At 50 emails/day checked: **~$0.09/day**, **~$2.70/month**.

This is negligible. We can classify every UNSEEN email without worrying about cost.

**Optimization:** Skip the LLM for emails that match thread IDs (Strategy 1 from Section 3). Those are guaranteed to be recruitment-related replies. Only run the LLM classifier on emails that don't match by thread ID.

### 6.4 Two-Stage vs. Single-Stage Classification

**Option A: Single LLM call (recommended)**
- One call that classifies AND extracts structured data.
- Simpler, fewer API calls, the extraction context helps classification.

**Option B: Two-stage**
- First call: binary "is this recruitment?" classifier.
- Second call (only for recruitment emails): full structured extraction.
- Theoretically saves cost on non-recruitment emails, but at $0.0018/email it doesn't matter.

**Go with Option A.** One call, one Pydantic model, done.

---

## 7. Recommended Architecture

### 7.1 New Modules

```
src/emplaiyed/
    inbox/
        __init__.py
        config.py        # ImapConfig model, auth helpers
        monitor.py       # Core polling + processing logic
        classifier.py    # LLM-based email classification
        matcher.py       # Match emails to applications
    cli/
        inbox_cmd.py     # CLI: emplaiyed inbox check / emplaiyed inbox setup
```

### 7.2 New Dependencies

```toml
# pyproject.toml additions
"imapclient>=3.0",
"html2text>=2024.2",
```

Optional (for OAuth2, phase 2):
```toml
"google-auth-oauthlib>=1.0",   # Gmail OAuth2
"msal>=1.0",                    # Outlook OAuth2
```

### 7.3 New Database Tables

```sql
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id          TEXT PRIMARY KEY,
    mailbox             TEXT NOT NULL,
    folder              TEXT NOT NULL,
    from_addr           TEXT,
    subject             TEXT,
    received_at         TEXT,
    processed_at        TEXT NOT NULL,
    matched_application_id TEXT,
    classification      TEXT,
    raw_classification  TEXT,   -- JSON of full EmailClassification
    FOREIGN KEY (matched_application_id) REFERENCES applications(id)
);
```

### 7.4 New Enum Values

Add to `WorkType`:
```python
class WorkType(str, Enum):
    OUTREACH = "OUTREACH"
    FOLLOW_UP = "FOLLOW_UP"
    NEGOTIATE = "NEGOTIATE"
    ACCEPT = "ACCEPT"
    REVIEW_RESPONSE = "REVIEW_RESPONSE"   # NEW: review an incoming email
```

### 7.5 Configuration

Add to `.env`:
```bash
# Email monitoring
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=your.email@gmail.com
IMAP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # Gmail App Password
```

Or add `imap_config` to the Profile model alongside `smtp_config`:
```python
class ImapConfig(BaseModel):
    host: str
    port: int = 993
    user: str
    password: str  # App password for MVP; OAuth2 later
```

### 7.6 CLI Interface

```bash
# Check for new emails, classify, match, create work items
emplaiyed inbox check

# Interactive setup of IMAP credentials
emplaiyed inbox setup

# Show processing history
emplaiyed inbox history
```

### 7.7 Processing Flow (Pseudocode)

```python
async def check_inbox(db_conn, profile):
    """Main entry point for inbox monitoring."""
    imap_config = load_imap_config()  # from .env or profile

    with IMAPClient(imap_config.host, ssl=True) as client:
        client.login(imap_config.user, imap_config.password)
        client.select_folder("INBOX")

        # Get UNSEEN messages
        uids = client.search(["UNSEEN"])
        if not uids:
            print("No new messages.")
            return

        messages = client.fetch(uids, ["RFC822", "FLAGS"])

        for uid, data in messages.items():
            raw = data[b"RFC822"]
            metadata = extract_email_metadata(raw)
            message_id = metadata["message_id"]

            # Dedup check
            if is_already_processed(db_conn, message_id):
                continue

            body_text = extract_email_text(raw)

            # Try thread matching first (free, high confidence)
            app_id = match_by_thread_id(db_conn, metadata)

            if app_id:
                # Direct reply to our outreach — skip LLM classification
                classification = EmailClassification(
                    is_recruitment=True,
                    category=EmailCategory.RESPONSE_POSITIVE,
                    summary=f"Reply to outreach: {metadata['subject']}",
                    ...
                )
            else:
                # Classify with LLM
                classification = await classify_email(
                    metadata, body_text, get_active_applications(db_conn)
                )

            if not classification.is_recruitment:
                record_processed(db_conn, message_id, classification=classification)
                continue

            # Match to application (if not already matched by thread)
            if not app_id:
                app_id = match_by_domain(db_conn, metadata["from"])
                if not app_id:
                    app_id = await match_by_llm(db_conn, metadata, body_text)

            if app_id:
                # Record interaction
                save_interaction(db_conn, Interaction(
                    application_id=app_id,
                    type=InteractionType.EMAIL_RECEIVED,
                    direction="inbound",
                    channel="email",
                    content=body_text,
                    metadata={
                        "message_id": message_id,
                        "from": metadata["from"],
                        "subject": metadata["subject"],
                        "classification": classification.model_dump(),
                    },
                    created_at=datetime.now(),
                ))

                # Create work item
                create_review_work_item(db_conn, app_id, classification)

                # Transition application status
                transition_on_response(db_conn, app_id, classification)

            # Mark processed
            record_processed(db_conn, message_id, app_id, classification)
            client.add_flags(uid, [b"\\Seen"])

        print(f"Processed {len(messages)} new emails.")
```

### 7.8 Work Item Creation

When a recruitment email is matched, create a work item for the user to review:

```python
def create_review_work_item(db_conn, app_id, classification):
    """Create a work item for reviewing an incoming email response."""
    opp = get_opportunity_for_application(db_conn, app_id)

    urgency_prefix = "[URGENT] " if classification.urgency == "urgent" else ""
    title = f"{urgency_prefix}Response from {opp.company} — {classification.summary}"

    next_steps = classification.next_steps or "Review the email and decide on next action."
    interview_info = ""
    if classification.interview_date:
        interview_info = f"\n**Proposed interview date:** {classification.interview_date}\n"

    instructions = (
        f"## {opp.company} responded to your application for {opp.title}\n\n"
        f"**Category:** {classification.category.value}\n"
        f"**Contact:** {classification.contact_name or 'Unknown'}"
        f" ({classification.contact_title or 'Unknown role'})\n"
        f"{interview_info}\n"
        f"### Summary\n{classification.summary}\n\n"
        f"### Next Steps\n{next_steps}\n\n"
        f"### What to do\n"
        f"1. Read the full email in your inbox\n"
        f"2. Take the recommended action above\n"
        f"3. Run: `emplaiyed work done <id>`\n"
    )

    create_work_item(
        db_conn,
        application_id=app_id,
        work_type=WorkType.REVIEW_RESPONSE,
        title=title,
        instructions=instructions,
        target_status=ApplicationStatus.RESPONSE_RECEIVED,
        previous_status=current_app_status,
        pending_status=current_app_status,  # don't change status until reviewed
    )
```

### 7.9 State Transitions on Response

When an email is classified, the application status should be updated based on the category:

| Email Category | Status Transition |
|---------------|-------------------|
| `INTERVIEW_INVITATION` | current -> `RESPONSE_RECEIVED` (work item created to schedule) |
| `RESPONSE_POSITIVE` | current -> `RESPONSE_RECEIVED` |
| `RESPONSE_NEGATIVE` | current -> `REJECTED` |
| `APPLICATION_ACKNOWLEDGMENT` | No transition (just log the interaction) |
| `OFFER` | current -> `OFFER_RECEIVED` |

For interview invitations specifically, also create a `ScheduledEvent` if the LLM extracted a date.

---

## 8. Implementation Estimate

| Task | Time |
|------|------|
| IMAP config model + `.env` loading + `inbox setup` CLI command | 30 min |
| Email fetching with IMAPClient (connect, search, fetch, dedup) | 45 min |
| Email parsing (MIME text extraction, metadata extraction) | 30 min |
| LLM classifier (prompt, Pydantic model, integration) | 45 min |
| Application matcher (thread ID, domain, LLM fallback) | 45 min |
| Work item creation + state transitions | 30 min |
| Database migration (processed_emails table, WorkType enum) | 20 min |
| `inbox check` CLI command (wires everything together) | 30 min |
| Tests (unit + integration with real IMAP) | 1.5 hours |
| **Total** | **~6 hours** |

This assumes AI-assisted development (Claude Code), familiarity with the codebase, and following the existing patterns (which are well-established).

---

## 9. Risks and Open Questions

1. **App Password deprecation risk.** Google could remove App Passwords in the future. If this happens, we'd need the full OAuth2 flow. The auth layer is isolated, so swapping it out would be straightforward.

2. **Multi-provider support.** If the user has Gmail for personal and Outlook for work, we'd need to support multiple IMAP configs. For MVP, support one mailbox.

3. **False positive matching.** An email from "recruiter@company.com" might match the wrong application if the user has multiple applications at the same company. The LLM fallback handles this, but it should present uncertain matches as "possible match" for human review rather than auto-linking.

4. **Email volume.** If the user gets 200+ emails/day, classifying all UNSEEN emails could be slow and costly (~$0.36/day). Mitigation: add a date filter (only check emails from the last N hours) and/or a sender allowlist.

5. **Rate limiting.** Gmail limits IMAP connections. One connection every 15 minutes is well within limits. Don't open multiple simultaneous connections.

6. **Privacy.** All email content passes through the LLM (OpenRouter). This is the same trust model as the rest of the tool (job descriptions, outreach drafts, etc.), but worth noting. Users who are uncomfortable with this could use a local LLM for classification.
