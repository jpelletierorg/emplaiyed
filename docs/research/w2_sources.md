# Week 2 Research: Job Board Sources for Canadian Tech Job Search

**Date:** 2026-02-16
**Context:** Sources for a bilingual (FR/EN) Lead Cloud Architect in Longueuil, QC seeking Applied AI Engineer roles, 70k-130k CAD, Montreal area, any work arrangement. Skills: Python, SQL, JS/TS, Java, Go, AWS, GCP, Azure, Docker, Terraform.

**Current state:** One working scraper (Job Bank Canada via httpx+BS4), one stub (Emploi Quebec -- needs browser automation).

---

## 1. Jobillico (jobillico.com)

### Overview
Jobillico is a Quebec-founded job board (HQ: Quebec City). It is strongly Quebec/Canada focused, making it highly relevant for Montreal-area searches. It is one of the largest job boards in Quebec and has significant francophone employer adoption.

### URL Structure for Searches
Jobillico uses clean, path-based URLs for searches:

- **By keyword:** `https://www.jobillico.com/search-jobs/{keyword-slug}`
  - Example: `https://www.jobillico.com/search-jobs/developer`
  - Example: `https://www.jobillico.com/search-jobs/python-developer`

- **By keyword + location:** `https://www.jobillico.com/search-jobs/{keyword-slug}/{city}/{province}`
  - Example: `https://www.jobillico.com/search-jobs/developer/montreal/quebec`
  - Example: `https://www.jobillico.com/search-jobs/web-developer/montreal/quebec`
  - Example: `https://www.jobillico.com/search-jobs/php-developer/montreal/quebec`

- **By location only:** `https://www.jobillico.com/search-jobs/{city}/{province}`
  - Example: `https://www.jobillico.com/search-jobs/montreal/quebec`

- **With query parameters (advanced):**
  ```
  https://www.jobillico.com/search-jobs/2?skwd=Administrative+Officer&scty=Montreal%2C+QC&icty=6185&ipc=0&flat=45.509828&flng=-73.6715&mfil=40&imc1=0&imc2=0&isj=0&ipg=1&sort=date&type=
  ```
  Key parameters:
  - `skwd` -- Search keyword
  - `scty` -- Search city (e.g., "Montreal, QC")
  - `icty` -- City ID (numeric)
  - `flat` / `flng` -- Latitude / Longitude
  - `mfil` -- Radius filter (in miles? unclear)
  - `ipg` -- Page number
  - `sort` -- Sort order (e.g., "date")
  - `type` -- Job type filter

### API
Jobillico has an official API, but it is designed for **employer-side operations** (posting jobs, managing listings), not for job search/scraping:

- **Pull (read) endpoint:** `https://www.jobillico.com/api/info` (POST, XML format)
- **Push (write) endpoint:** `https://www.jobillico.com/api/push` (POST, XML format)
- Requests are XML-encoded UTF-8, submitted via POST.
- Requires authentication (email + password credentials via OAuth).
- Sandbox environment by default; production access requires contacting Jobillico.
- API docs: https://www.jobillico.com/api/help/jobillico-api

The Pull API can retrieve information about locations, companies, jobs, recruiters, departments, and job functions. However, this API is intended for partner integrations (e.g., ATS systems posting jobs to Jobillico), not for consuming/searching job listings as a job seeker.

### Scraping Feasibility Assessment

**Verdict: Likely feasible with httpx+BS4, but needs verification.**

- The clean URL structure (`/search-jobs/keyword/city/province`) strongly suggests server-side rendering for SEO purposes. Job boards with this kind of URL pattern typically render initial HTML server-side.
- The query parameter variant also supports pagination (`ipg=`) which is a good sign for scraping.
- However, I could not directly verify whether results are loaded via JavaScript after initial page load. **The implementation should start with an httpx fetch of a search URL and inspect whether job listings appear in the raw HTML.** If they do, httpx+BS4 is sufficient. If not, Playwright would be needed.
- Keyword slugs appear to be hyphenated lowercase versions of search terms (e.g., "python developer" -> "python-developer").

### Implementation Approach
```python
# Construct search URL
keyword_slug = "-".join(keywords).lower()  # e.g., "python-developer"
url = f"https://www.jobillico.com/search-jobs/{keyword_slug}/montreal/quebec"

# Pagination via query params
url_paged = f"https://www.jobillico.com/search-jobs/2?skwd=python+developer&scty=Montreal%2C+QC&ipg={page}&sort=date"
```

### Estimated Implementation Effort
- If httpx+BS4 works: **2-3 hours** (build URL, parse results HTML, parse detail pages, write tests)
- If JS-rendered (needs Playwright): **4-6 hours** (add Playwright dependency, headless browser setup, same parsing)

### Relevance: HIGH
Quebec-focused, strong francophone employer base, likely to surface Montreal-area roles not found on national boards.

---

## 2. Talent.com (ca.talent.com)

### Overview
Talent.com (formerly Neuvoo) is a Canadian-founded job aggregator based in Montreal. It aggregates listings from other job boards and company career pages. Covers 78+ countries with a strong Canadian presence. Very relevant for Montreal tech searches.

### URL Structure
Talent.com Canada uses `ca.talent.com` as its domain with a clean path-based URL structure:

- **By keyword + location:** `https://ca.talent.com/jobs/k-{keyword}-l-{city}-{province}`
  - Example: `https://ca.talent.com/jobs/k-python-l-montreal-qc`
  - Example: `https://ca.talent.com/jobs/k-software-engineer-l-montreal-qc`
  - Example: `https://ca.talent.com/jobs/k-entry-level-machine-learning-l-montreal-qc`

- **With query parameters:** `https://ca.talent.com/jobs?k=python+perl+developer&l=montreal,+qc`

- **By location only:** `https://ca.talent.com/jobs/l-canada`

Keywords use hyphens as separators in the path form, or `+` in the query parameter form.

### Scraping Feasibility Assessment

**Verdict: Likely feasible with httpx+BS4, needs verification.**

- The clean SEO-friendly URL pattern (`/jobs/k-keyword-l-location`) suggests server-side rendered content.
- Being a job aggregator, Talent.com pulls from many sources, so it provides wide coverage.
- Third-party scrapers (Apify) exist for Talent.com, which confirms the data is extractable.
- Anti-bot measures are likely moderate. Rate limiting is important.
- No public API for job search.

### Implementation Approach
```python
keyword_slug = "-".join(keywords).lower().replace(" ", "-")
url = f"https://ca.talent.com/jobs/k-{keyword_slug}-l-montreal-qc"
# Pagination: likely via ?p=2 or &p=2 query parameter
```

### Estimated Implementation Effort
- If httpx+BS4 works: **2-3 hours**
- If JS-rendered: **4-6 hours** with Playwright

### Relevance: HIGH
Montreal-founded aggregator, excellent Canadian coverage, aggregates from many sources so provides broad reach with a single scraper.

---

## 3. Indeed Canada (indeed.ca)

### Overview
Largest job board globally. Massive Canadian presence. Would surface the most listings.

### Scraping Feasibility Assessment

**Verdict: NOT feasible with httpx+BS4. Heavy anti-bot protection.**

- Indeed is protected by Cloudflare's enterprise-grade bot management.
- Aggressive rate limiting, JavaScript challenges, CAPTCHA (Turnstile), TLS fingerprinting.
- Even accessing `robots.txt` returns 403 in some contexts.
- The JobSpy library notes Indeed is "the best scraper currently with no rate limiting" but this relies on carefully rotated proxies and specific evasion techniques that would add significant complexity.
- Indeed's Terms of Service explicitly prohibit scraping.

### Recommendation
**~~Skip for now.~~  IMPLEMENTED (2026-02-20) via python-jobspy.**

The original assessment that direct httpx+BS4 scraping is infeasible remains
correct.  However, the [python-jobspy](https://github.com/speedyapply/JobSpy)
library (v1.1.82, MIT licensed, actively maintained) handles Indeed's TLS
fingerprinting and anti-bot measures transparently.  We wrap it as
`IndeedSource` in `sources/indeed.py`, targeting `country_indeed="Canada"`.

Key implementation details:
- `scrape_jobs(site_name=["indeed"], country_indeed="Canada", ...)` is
  synchronous, so we run it via `asyncio.to_thread()`.
- Salary normalisation (hourly/daily/weekly/monthly -> annual) is handled
  in our mapping layer.
- No proxies required at current usage levels (jobspy docs note Indeed has
  no rate limiting).
- Adds ~50 MB of dependencies (pandas, numpy, tls-client).

### Estimated Implementation Effort
- ~~**8-16+ hours** with ongoing maintenance burden and proxy costs.~~
- **Actual: ~3 hours** using python-jobspy as the scraping backend.

### Relevance: HIGH (content), ~~LOW (feasibility)~~ HIGH (via python-jobspy)

---

## 4. LinkedIn Job Search

### Overview
Large volume of tech job postings, especially for senior roles.

### Scraping Feasibility Assessment

**Verdict: NOT feasible for our use case.**

- Public job listings are accessible without login using specific URL patterns, but LinkedIn employs multiple protection layers: rate limiting (blocks around page 10), IP bans, browser fingerprinting, CAPTCHA.
- Maximum 1,000 results per query even when it works.
- LinkedIn's Terms of Service explicitly prohibit scraping.
- While the HiQ Labs v. LinkedIn ruling in the US found scraping public data does not violate computer fraud laws, it remains legally contentious in Canada.
- Would require proxy rotation and careful rate limiting.

### Recommendation
**Skip.** Too much anti-bot engineering for the value. Many LinkedIn-posted jobs also appear on other boards.

### Estimated Implementation Effort
- **12-20+ hours** with proxy requirements and ongoing maintenance.

### Relevance: HIGH (content), LOW (feasibility)

---

## 5. Jooble (jooble.org) -- RECOMMENDED

### Overview
Jooble is a major job aggregator (covers 71 countries) that provides a **free REST API** for job search. This is the single best source to add for coverage breadth with minimal implementation effort.

### API Details

- **Endpoint:** `POST https://jooble.org/api/{api_key}`
- **Registration:** Free at https://jooble.org/api/about
- **Request format:** JSON POST body
- **Response format:** JSON

**Request body:**
```json
{
    "keywords": "python developer",
    "location": "Montreal",
    "radius": "40",
    "salary": "70000",
    "page": "1"
}
```

**Request parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `keywords` | Yes | Search terms (e.g., "python developer, AI engineer") |
| `location` | Yes | City/region (e.g., "Montreal") |
| `radius` | No | Search radius in km. Values: 0, 4, 8, 16, 26, 40, 80 |
| `salary` | No | Minimum salary for job search |
| `page` | No | Page number of search results |
| `ResultOnPage` | No | Number of jobs per page |
| `companysearch` | No | Boolean - search by company name |

**Response fields per job:**
- `title` -- Job title
- `location` -- Job location
- `snippet` -- Description snippet
- `salary` -- Salary info
- `source` -- Original source site
- `type` -- Job type
- `link` -- URL to original posting
- `company` -- Company name
- `updated` -- Last updated date
- `id` -- Jooble job ID
- `totalCount` -- Total matching results

### Scraping Feasibility Assessment

**Verdict: TRIVIAL. Free REST API with JSON responses. No HTML parsing needed.**

- No scraping required -- this is an official API.
- Free API key registration.
- Generous rate limits for personal use.
- Aggregates from Indeed, LinkedIn, Glassdoor, and hundreds of other sources.
- Returns structured JSON -- no BeautifulSoup needed.
- Works with plain `httpx` POST requests.

### Implementation Approach
```python
import httpx

API_KEY = "your_api_key"
url = f"https://jooble.org/api/{API_KEY}"
payload = {
    "keywords": "python developer",
    "location": "Montreal",
    "radius": "40",
    "page": "1"
}
async with httpx.AsyncClient() as client:
    response = await client.post(url, json=payload)
    data = response.json()
    # data["jobs"] is a list of job dicts
    # data["totalCount"] is total results
```

### Estimated Implementation Effort
- **1-2 hours** (register API key, implement source, write tests)

### Relevance: VERY HIGH
Aggregates from many sources including Indeed, LinkedIn, Glassdoor, and local boards. One API gives access to hundreds of sources. Best effort-to-coverage ratio of any source.

---

## 6. GC Digital Talent (talent.canada.ca)

### Overview
Government of Canada's recruitment platform for digital and IT jobs in federal government. Launched 2024, already has 16,000+ applicant profiles and ran 64 recruitment campaigns.

### Scraping Feasibility Assessment

**Verdict: Possible but low priority.**

- Open-source codebase (GitHub: GCTC-NTGC/gc-digital-talent), which means the data model and API structure are known.
- The platform uses a separate API and frontend architecture.
- However, the volume of listings is low (dozens, not thousands) and they are government-specific roles.
- Jonathan's profile targets private sector primarily.

### Recommendation
**Skip for now.** Low volume of listings and government-specific. Can be added later if government roles become a priority.

### Estimated Implementation Effort
- **3-4 hours** (study open-source API, implement source)

### Relevance: LOW (for private sector AI/cloud roles)

---

## 7. Glassdoor

### Scraping Feasibility Assessment

**Verdict: NOT feasible.**

- Protected by Cloudflare enterprise bot management.
- No public API.
- Requires login for most content.
- Multiple anti-scrape protection layers.
- Terms of Service prohibit scraping.

### Recommendation
**Skip.** Covered by Jooble aggregation.

---

## 8. Other Sources Considered

### Wellfound (formerly AngelList)
- Startup-focused job board.
- "Notorious for blocking all web scrapers."
- Not feasible with httpx+BS4.
- Limited Canadian/Montreal startup listings.
- **Skip.**

### Workopolis / Monster Canada
- Workopolis was acquired by Indeed in 2019 and redirects to Indeed.
- Monster Canada has limited presence.
- **Skip.** Covered by Jooble.

### Techjobs.ca
- Canadian tech-specific job board.
- Unknown scraping feasibility (could not verify server-side rendering).
- Low volume compared to aggregators.
- **Low priority -- investigate later.**

### Built In Montreal (builtinmontreal.com)
- Montreal-specific tech and startup jobs.
- Unknown scraping feasibility.
- Niche but relevant for Montreal tech.
- **Low priority -- investigate later.**

### Communitech Work In Tech (www1.communitech.ca/jobs)
- Ontario-focused tech job board.
- Less relevant for Montreal.
- **Skip.**

---

## 3. Legal/Ethical Considerations

### robots.txt Compliance
- **Always check and respect robots.txt** before scraping any source.
- Recheck robots.txt before each crawl session or at least once per day.
- robots.txt is not legally binding but is treated as a consent signal by courts and regulators.
- Cache robots.txt and refresh at scheduled intervals.

### Rate Limiting Best Practices
- **1-3 seconds between requests** to the same domain (mimic human browsing).
- Add random jitter to delays (e.g., `1.0 + random.uniform(0, 2.0)` seconds).
- Respect `Crawl-delay` directives in robots.txt.
- Monitor server response times -- if responses slow down, back off.
- Implement exponential backoff on 429 (Too Many Requests) or 503 responses.
- Cap concurrent requests per domain to 1 (sequential, not parallel).

### Terms of Service
- Most job boards explicitly prohibit automated scraping in their ToS.
- For **personal, non-commercial job search use**, the legal risk is minimal, but ToS violations could result in IP blocking.
- The Jooble API is the cleanest legal path -- it's an authorized API for exactly this use case.
- Government sites (Job Bank Canada) are public data and generally more permissive.

### Canadian Legal Context
- Canada's PIPEDA applies to personal data collection but job postings are not personal data.
- Job listings are generally considered publicly available information.
- The key risk is ToS violation leading to IP blocks, not legal action, for personal use at low volume.

### Our Approach
1. **Use official APIs where available** (Jooble, Job Bank).
2. **Respect robots.txt** for scraped sites (Jobillico, Talent.com).
3. **Rate limit aggressively** -- we are not building a real-time system; once-daily scraping with polite delays is fine.
4. **Set a proper User-Agent** identifying our tool.
5. **Do not bypass authentication walls, CAPTCHAs, or JavaScript challenges.**

---

## 4. Recommended Implementation Order

Priority is based on: (relevance to profile) x (listing volume) / (implementation effort).

### Tier 1: Implement This Week

| # | Source | Effort | Why |
|---|--------|--------|-----|
| 1 | **Jooble API** | 1-2 hours | Free REST API, JSON responses, aggregates from hundreds of sources including Indeed/LinkedIn/Glassdoor. Best ROI of any source. Register at https://jooble.org/api/about |
| 2 | **Jobillico** | 2-3 hours | Quebec-focused, high relevance for Montreal. Clean URL structure. Needs HTML verification first. |

### Tier 2: Implement Next Week

| # | Source | Effort | Why |
|---|--------|--------|-----|
| 3 | **Talent.com** | 2-3 hours | Montreal-founded aggregator, clean URL structure, good Canadian coverage. Some overlap with Jooble but different source mix. |

### Tier 3: Investigate Later

| # | Source | Effort | Why |
|---|--------|--------|-----|
| 4 | Built In Montreal | Unknown | Montreal-specific tech jobs, niche but relevant. Need to verify feasibility. |
| 5 | Techjobs.ca | Unknown | Canadian tech-specific. Need to verify feasibility. |
| 6 | GC Digital Talent | 3-4 hours | Government digital roles only. Low volume. |

### Sources to Skip

| Source | Reason |
|--------|--------|
| ~~Indeed Canada~~ | ~~Cloudflare enterprise protection. Covered by Jooble.~~ **Now integrated via python-jobspy (2026-02-20).** |
| LinkedIn | Heavy anti-bot measures. Covered partially by Jooble. |
| Glassdoor | Cloudflare protection, login required. Covered by Jooble. |
| Wellfound | Aggressive anti-scraping. Limited Canadian presence. |
| Workopolis | Redirects to Indeed. |
| Monster Canada | Limited presence. Covered by Jooble. |

### Summary: Expected Coverage After Tier 1+2

With Job Bank + Jooble + Jobillico + Talent.com, we would cover:
- **Direct government listings** (Job Bank)
- **Hundreds of aggregated sources** (Jooble -- pulls from Indeed, LinkedIn, Glassdoor, etc.)
- **Quebec-specific employers** (Jobillico -- francophone employers who post primarily here)
- **Canadian aggregation** (Talent.com -- Montreal-founded, strong Canadian employer relationships)

This combination should surface the vast majority of relevant Montreal-area AI/cloud/backend roles within about 6-8 hours of total implementation work.

---

## Appendix: Quick Reference URLs

### Jobillico Example Searches
```
https://www.jobillico.com/search-jobs/python-developer/montreal/quebec
https://www.jobillico.com/search-jobs/cloud-architect/montreal/quebec
https://www.jobillico.com/search-jobs/ai-engineer/montreal/quebec
```

### Talent.com Example Searches
```
https://ca.talent.com/jobs/k-python-developer-l-montreal-qc
https://ca.talent.com/jobs/k-cloud-architect-l-montreal-qc
https://ca.talent.com/jobs/k-ai-engineer-l-montreal-qc
```

### Jooble API
```
Registration: https://jooble.org/api/about
Docs: https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation
Endpoint: POST https://jooble.org/api/{api_key}
```

### Jobillico API (employer-side, NOT for job search)
```
Docs: https://www.jobillico.com/api/help/jobillico-api
Info endpoint: POST https://www.jobillico.com/api/info
```
