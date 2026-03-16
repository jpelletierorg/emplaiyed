# W3 Research: What Makes CVs and Cover Letters Actually Effective

**Purpose:** Evidence-based research to improve our AI-generated CV and cover letter quality.
**Date:** 2026-02-16

---

## Table of Contents

1. [ATS Parsing and Ranking](#1-ats-parsing-and-ranking)
2. [Recruiter Reading Behavior](#2-recruiter-reading-behavior)
3. [Cover Letter Effectiveness](#3-cover-letter-effectiveness)
4. [Keyword Optimization](#4-keyword-optimization)
5. [Bilingual Considerations (Quebec)](#5-bilingual-considerations-quebec)
6. [Format and Length](#6-format-and-length)
7. [AI Detection and Authenticity](#7-ai-detection-and-authenticity)
8. [Gaps in Our Current Prompts](#8-gaps-in-our-current-prompts)
9. [Recommended Changes](#9-recommended-changes)

---

## 1. ATS Parsing and Ranking

### How ATS Actually Works

98% of Fortune 500 companies use ATS software. The system extracts text, organizes it into fields (name, contact, work experience, education, skills), compares against the job description, scores based on keyword matches, and forwards only the highest-scoring resumes (typically top 25%) to human recruiters. ([The Interview Guys](https://blog.theinterviewguys.com/what-ats-looks-for-in-resumes/), [SGS Consulting](https://sgsconsulting.com/blogs/a-2025-guide-to-building-an-ats-optimized-resume))

### Key Statistics

- **99.7%** of recruiters use keyword filters in their ATS to sort and prioritize applicants (Jobscan State of the Job Search 2025).
- **76.4%** of recruiters filter candidates by skills from the job description.
- **55.3%** use job titles as a keyword filter.
- **44%** filter by years of experience.
- **43.4%** filter by location.
- Candidates whose resume job title **matches the target title** had an interview rate **10.6x higher** than those who did not.

Sources: [Jobscan State of Job Search 2025](https://www.jobscan.co/state-of-the-job-search), [The Interview Guys](https://blog.theinterviewguys.com/state-of-job-search-2025-research-report/)

### Formatting That Helps vs. Hurts

| Factor | Recommendation | Why |
|--------|---------------|-----|
| **File format** | DOCX preferred; text-based PDF acceptable | DOCX parses most reliably across all ATS. Modern ATS (Greenhouse, Lever, Workday) can read clean PDFs, but DOCX is the safer default. |
| **Layout** | Single-column for all core sections | Two-column layouts can cause ATS to read content out of order or skip content entirely. |
| **Tables** | Avoid entirely | ATS may scramble cell content, skip cells, or misplace keywords. |
| **Text boxes** | Avoid entirely | Often treated as graphical elements; many ATS ignore content inside them. |
| **Headers/footers** | Do NOT put contact info here | 25% of ATS fail to parse header/footer content (TopResume). |
| **Section headings** | Use standard names | "Work Experience", "Education", "Skills", "Certifications" are universally recognized. Creative headings ("Career Journey", "Where I've Been") confuse ATS. |
| **Fonts** | Standard fonts only | Arial, Calibri, Helvetica, Georgia, Times New Roman. |
| **Bullet style** | Standard bullets only | Decorative symbols, emojis, and custom glyphs can break parsing. |
| **Contact info** | In main document body, top of page | Single line or two-line layout, separated by vertical bars or line breaks. |

Sources: [Jobscan](https://www.jobscan.co/blog/ats-formatting-mistakes/), [TopResume](https://topresume.com/career-advice/what-is-an-ats-resume), [Resumly](https://www.resumly.ai/blog/ats-friendly-resume-templates-2025), [Resumemate](https://www.resumemate.io/blog/two-column-resumes-ats-tests-workarounds-and-examples/)

### Implications for Our System

Our current PDF rendering uses WeasyPrint to convert HTML to PDF. The generated PDF is text-based (not image-based), which is good. However:

1. **The colored header band** uses CSS that renders as a visual element. We need to verify that ATS can still extract the text within it. The `<div class="header">` contains name, title, and contact info -- all critical for parsing.
2. **Skill pills** use `<span>` elements with CSS styling. These should parse as text, but the inline-block layout with rounded backgrounds could confuse some parsers.
3. **The custom bullet character** `"▸"` (inserted via CSS `::before`) may not be recognized by all ATS. Standard bullet characters are safer.
4. **We only generate PDF.** We should also offer DOCX output as the primary ATS-submission format, with PDF as the human-readable version.

---

## 2. Recruiter Reading Behavior

### The Initial Scan

The widely cited "6-second scan" has been updated by more recent research:

- **TheLadders eye-tracking study (2018):** Average initial glance of **7.4 seconds**. Consistent F-pattern scan (top of page, then down the left side).
- **InterviewPal data study (2025):** Analyzed 4,289 resume reviews across 312 recruiters. Found an average initial scan time of **11.2 seconds** -- notably higher than the 6-8 second benchmark. Recruiters using AI-assisted or structured review tools spent longer on the first pass.

Sources: [TheLadders](https://www.bu.edu/com/files/2018/10/TheLadders-EyeTracking-StudyC2.pdf), [InterviewPal](https://www.interviewpal.com/blog/how-long-recruiters-actually-spend-reading-your-resume-data-study), [Standout CV](https://standout-cv.com/usa/stats-usa/how-long-recruiters-spend-looking-at-resume)

### What Gets Looked At

**80% of the initial scan time** is spent on:
1. Name
2. Current title/company
3. Previous titles/companies
4. Start and stop dates of employment
5. Education

Source: [TheLadders](https://www.bu.edu/com/files/2018/10/TheLadders-EyeTracking-StudyC2.pdf)

### The F-Pattern

Recruiters scan in an F-pattern: they read across the top of the page, then scan down the left margin. This means:

- **The top third of page 1 is the most valuable real estate.** Name, title, summary, and top skills must be there.
- **Left-aligned content gets seen first.** Job titles, company names, and dates should be left-aligned or prominently placed.
- **Bullet point beginnings matter more than endings.** The first 2-3 words of each bullet are what gets scanned.

Sources: [Medium - F-Pattern](https://tripathiadityaprakash.medium.com/the-f-pattern-secret-how-to-design-a-resume-that-survives-the-6-second-scan-08adcd62a934), [Barclay Simpson](https://www.barclaysimpson.com/how-long-do-recruiters-spend-looking-at-cv/)

### Implications for Our System

Our current CV structure (name > professional title > contact > summary > skills > experience) aligns well with F-pattern expectations. However:

1. **Professional summary:** Our prompt says "2 sentences." Given that summaries with quantified achievements get 340% more callbacks, we should ensure these 2 sentences are metric-laden.
2. **Action verb starts on bullets:** Our prompt already emphasizes strong action verbs. Good -- the first word of each bullet is what gets scanned.
3. **Current title prominence:** The `professional_title` field appears right under the name in our template. This is correct placement for F-pattern scanning.

---

## 3. Cover Letter Effectiveness

### Do They Matter?

Yes, but conditionally.

| Statistic | Source |
|-----------|--------|
| **83%** of hiring managers read cover letters even when not required | [The Interview Guys](https://blog.theinterviewguys.com/cover-letters-are-making-a-comeback/) |
| **45%** of hiring managers review cover letters *before* resumes | [The Interview Guys](https://blog.theinterviewguys.com/cover-letters-are-making-a-comeback/) |
| **94%** say cover letters influence interview decisions | [Resume Genius](https://resumegenius.com/blog/cover-letter-help/cover-letter-statistics) |
| **81%** said they value tailored letters much more than generic ones | [Resume Genius](https://resumegenius.com/blog/cover-letter-help/cover-letter-statistics) |
| **60%** spend 2+ minutes reading cover letters | [Staffing by Starboard](https://staffingbystarboard.com/blog/cover-letters-in-2026-still-worth-writing/) |
| Cover letters matter most for **senior/strategic roles** | [HBR](https://hbr.org/2025/03/cover-letters-still-matter-even-if-theyre-not-required) |
| Most recruiters do **NOT** read cover letters during initial screening for high-volume roles | Multiple sources |

### When They Matter Most

- Senior, management, or strategic roles (Jonathan's target level)
- When candidates are being shortlisted or compared closely
- When the role requires communication skills
- When submitted directly to a hiring manager (vs. ATS upload)

Source: [HBR](https://hbr.org/2025/03/cover-letters-still-matter-even-if-theyre-not-required)

### Optimal Length

**Our current target: 150 words. Research consensus: 250-400 words.**

| Research Finding | Source |
|-----------------|--------|
| 76% of hiring managers prefer cover letters that are **half a page or less** (~250-400 words) | TheLadders |
| Ideal range is **250-400 words** in 3-4 paragraphs | [Wobo](https://www.wobo.ai/blog/how-long-should-a-cover-letter-be-2025/), [Zety](https://zety.com/blog/how-long-should-a-cover-letter-be), [Cover Letter Copilot](https://coverlettercopilot.ai/blog/how-many-words-should-a-cover-letter-be) |
| Senior-level candidates should keep it concise but focus on key achievements -- still within one page | [Cover Letter Copilot](https://coverlettercopilot.ai/blog/how-long-should-a-cover-letter-be) |
| Recruiters spend **30-60 seconds** reviewing a cover letter before deciding whether to continue | [Global English Test](https://globalenglishtest.com/cover-letter-word-count-finding-the-perfect-length/) |

**Verdict:** 150 words is too short. It signals either low effort or inability to articulate value. **Increase target to 200-300 words.** This keeps the punchy, no-fluff tone while giving enough space for a compelling hook, concrete proof, and a confident close. Going to 400 words risks padding.

### Most Effective Structure

Three approaches have evidence behind them, and they are complementary:

**1. Three-Paragraph Formula** (our current approach):
- Paragraph 1: Hook -- why this company/role
- Paragraph 2: Proof -- 2-3 compelling reasons you can excel
- Paragraph 3: Close -- eagerness to discuss

**2. Pain-Point Formula:**
- Identify the company's specific problem/need
- Show how your experience solves that exact problem
- Include quantifiable metrics from your track record

**3. Storytelling Approach:**
- Open with a specific, memorable anecdote from your career
- Connect that story to the role's requirements
- Close with forward-looking enthusiasm

The pain-point approach is particularly effective for senior roles because it demonstrates strategic thinking. Our current prompt should incorporate elements of the pain-point formula.

Sources: [The Muse](https://www.themuse.com/advice/this-is-how-you-write-a-pain-point-cover-letter-examples-included), [The Interview Guys](https://blog.theinterviewguys.com/3-paragraph-cover-letter-formula/)

### HBR's Six-Part Template

Harvard Business Review recommends cover letters that:
1. Open with a specific, enthusiastic statement about why the role excites you
2. Connect your skills and experience to the job description
3. Mention relevant contacts or experiences with the company
4. Add supporting details (published work, unique skills)
5. Address potential resume concerns (gaps, transitions)
6. Close with excitement about contributing to the company's mission

Source: [HBR](https://hbr.org/2025/03/cover-letters-still-matter-even-if-theyre-not-required)

---

## 4. Keyword Optimization

### Beyond Simple Matching

Modern ATS systems (2025-2026) increasingly use NLP and AI for semantic analysis. They can understand context and meaning, not just exact string matches. However, exact phrasing still matters significantly.

### What Actually Improves Ranking

**1. Exact title matching is critical.**
Candidates with job titles matching the target title had an **interview rate 10.6x higher**. If the posting says "Applied AI Engineer," that exact phrase should appear in the resume.

**2. Skills from the job description, used in context.**
76.4% of recruiters filter by skills. But keywords paired with impact metrics score higher than keywords listed in isolation. "Deployed machine learning models reducing inference latency by 40%" beats "Machine Learning" in a skills list.

**3. Contextual keyword clustering.**
Group related terms together. Instead of scattering "Python," "TensorFlow," and "ML" across the resume, cluster them in achievement bullets: "Architected Python-based ML pipeline using TensorFlow, processing 2M daily predictions."

**4. The STAR-K method.**
Situation, Task, Action, Result + Keywords. Each achievement bullet naturally embeds relevant keywords while proving competence with quantified results.

**5. Match rate target: 65-80%.**
You do not need 100% keyword match. Aim for 65-80% of the job description's key terms. This is enough to rank in the top 25-30% of applicants.

### What Hurts

- **Keyword stuffing:** Modern ATS detects obvious repetition. It also triggers negative reactions from human readers.
- **White text / tiny font tricks:** Detectable and disqualifying.
- **Synonym-only approach:** ATS does not always recognize synonyms. Use the exact wording from the job description when it accurately describes your experience.
- **Keywords without context:** A "Skills" section listing keywords helps, but keywords embedded in achievement bullets carry more weight.

Sources: [Jobscan](https://www.jobscan.co/blog/top-resume-keywords-boost-resume/), [The Interview Guys](https://blog.theinterviewguys.com/ats-resume-optimization/), [SGS Consulting](https://sgsconsulting.com/blogs/a-2025-guide-to-building-an-ats-optimized-resume)

### Implications for Our System

Our current prompt says: "Mirror keywords from the job description naturally in the summary, skills, and experience bullets. Do not keyword-stuff." This is correct but too vague. We should:

1. **Explicitly instruct the LLM to include the exact job title** from the posting in the professional title or summary.
2. **Instruct the LLM to extract the top 5-10 skills** from the job description and ensure each appears at least once, preferably in an achievement context.
3. **Instruct the LLM to use exact phrasing** from the job description rather than synonyms, where the candidate genuinely has that skill.

---

## 5. Bilingual Considerations (Quebec)

### Language Matching Rules

**Write the CV in the same language as the job posting.** This is the dominant norm in Quebec.

- If the job ad is in French, submit in French.
- If the job ad is in English, submit in English.
- For bilingual postings, French is the safer default in Montreal.

Sources: [Resume Example](https://resume-example.com/cv/quebec), [Novoresume](https://novoresume.com/career-blog/canada-resume-format), [Maplr](https://maplr.co/en/rediger-un-cv-canadien/)

### Bill 96 Context (Effective June 1, 2025)

Quebec's Bill 96 strengthens French language requirements in the workplace:

- Employers must make job postings available in French.
- If a position requires knowledge of English, the employer must justify this in the posting.
- The law now applies to businesses with 25+ employees (previously 50+).
- All employment offers, contracts, and written communications to employees must be in French.

This means: for most Montreal tech jobs, expect French-first job postings. English-language postings exist but often signal that the employer has justified a bilingual requirement.

Sources: [McCarthy Tetrault](https://www.mccarthy.ca/en/insights/blogs/canadian-employer-advisor/employer-obligations-under-charter-french-language-coming-force-june-1-2025), [Lexpert](https://www.lexpert.ca/news/legal-insights/bill-96-hiring-process-in-quebec-can-employers-require-knowledge-of-a-language-other-than-french/390539), [DLA Piper](https://knowledge.dlapiper.com/dlapiperknowledge/globalemploymentlatestdevelopments/2025/Quebecs-language-laws-changed-this-week-Heres-what-you-need-to-know)

### Bilingualism as a Competitive Advantage

Being bilingual (French/English) is highly valued in Quebec's job market. Recommendations:

1. **Always list both languages prominently** in the Languages section, with proficiency levels.
2. **For English-language postings:** The CV should be in English, but prominently highlight French fluency as a differentiator. Many employers in Montreal need bilingual staff.
3. **For French-language postings:** Write in French. Highlight English proficiency.
4. **Do NOT submit two separate CVs** (one French, one English) unless specifically asked.

Sources: [Indeed Canada](https://ca.indeed.com/career-advice/resumes-cover-letters/bilingual-resume), [CVwizard](https://www.cvwizard.com/en/articles/bilingual-resume)

### Implications for Our System

**Major gap:** Our system currently generates CVs only in English. For the Quebec market, we need:

1. A mechanism to detect the job posting language and generate assets in the matching language.
2. French-language system prompts (or bilingual prompts with language selection).
3. The Languages section should always be prominent, not buried at the bottom. For Quebec, it should appear right after Skills or even in the header area.

---

## 6. Format and Length

### Resume Length: One Page vs. Two Pages

**For 10+ years of experience, two pages is preferred.**

| Finding | Source |
|---------|--------|
| **90%** of recruiters agree a 2-page resume is ideal for most roles | US recruiter survey |
| Recruiters are **2.3x more likely** to prefer two-page resumes for experienced candidates | CNBC / 2023 survey |
| For professionals with 8-15 years of experience, two pages is acceptable and expected | [Monster](https://www.monster.com/career-advice/article/one-page-or-two-page-resume), [Resumatic](https://www.resumatic.ai/articles/how-long-should-resume-be) |
| Rule of thumb: one page per 10 years of experience | [Enhancv](https://enhancv.com/blog/how-long-should-a-resume-be/) |
| What matters most is clarity and relevance, not raw page count | Multiple sources |

**Verdict:** Our current prompt says "Aim for 1-2 pages of content." This is correct but should lean toward 2 pages for Jonathan's experience level. A one-page CV for a 10+ year Lead Cloud Architect would look sparse and undersell the candidate.

Sources: [ResumeWorded](https://resumeworded.com/can-a-resume-be-two-pages-key-advice), [Resumly](https://www.resumly.ai/blog/how-long-should-a-resume-be)

### Professional Summary vs. Objective

- Resumes with professional summaries receive **340% more interview callbacks** than those with objectives.
- 78% of recruiters spend less than 10 seconds on the opening statement.
- Summaries with metrics and outcomes get more engagement.
- ATS scores summaries with quantified achievements and relevant keywords higher.

Source: [The Interview Guys](https://blog.theinterviewguys.com/resume-objective-vs-summary/)

**Our current approach (2-sentence summary) is correct.** But both sentences must contain quantifiable claims.

### Achievement Bullet Format

**CAR (Challenge-Action-Result) is preferred over STAR for resume bullets** because it is more concise and better suited to space constraints. Both are effective, but CAR produces tighter bullets.

Example CAR bullet:
> "Reduced cloud infrastructure costs by 35% ($120K/year) by architecting serverless migration across 12 microservices."

vs. a duty-based bullet:
> "Managed cloud infrastructure and performed migrations."

Sources: [Teal HQ](https://www.tealhq.com/post/car-method-resume), [Resume Giants](https://www.resumegiants.com/blog/achievements-resume/)

---

## 7. AI Detection and Authenticity

### The Detection Landscape

A 2026 Jobscan study found:
- **67%** of hiring managers say they can identify AI-generated content.
- **54%** view AI-generated content negatively.
- But those same managers **cannot detect AI content** that has been properly humanized with specific details and authentic voice.

Source: [Cover Letter Copilot](https://coverlettercopilot.ai/blog/are-ai-cover-letters-detectable-by-recruiters)

### Red Flags That Signal AI

1. **Overly formal, uniform language** -- AI tends to pick "safe" phrasing, making all letters sound the same.
2. **Generic phrases:** "results-oriented professional," "proven track record," "synergistic approach," "detail-oriented team player."
3. **Round numbers:** "Improved performance by 50%." Precise numbers ("Improved performance by 47%") feel more authentic.
4. **Interchangeability:** If you can swap the company name and nothing breaks, the letter is too generic.
5. **Perfect grammar throughout** -- real human writing has slight imperfections and personality.

### What Makes AI Content Pass

1. **Specific details** about the company, role, and candidate's actual experience.
2. **Precise (non-round) metrics** from real achievements.
3. **Varied sentence structure** -- mix short punchy sentences with longer ones.
4. **Personality** -- a recognizable voice, not corporate boilerplate.
5. **One specific anecdote or story** that only this candidate could tell.

Sources: [HRMLESS](https://www.hrmless.com/blog/do-hiring-managers-check-for-ai-in-cover-letters), [Cover Letter Copilot](https://coverlettercopilot.ai/blog/are-ai-cover-letters-detectable-by-recruiters), [AI Apply](https://aiapply.co/blog/can-employers-tell-if-you-use-ai-for-a-cover-letter)

### Implications for Our System

Our current letter prompt already avoids some corporate speak ("NO corporate speak. No 'I am writing to express my interest'"). But we should:

1. **Explicitly ban common AI-sounding phrases** in both CV and letter prompts.
2. **Instruct the LLM to use precise, non-round numbers** when quantifying achievements.
3. **Instruct the LLM to vary sentence length** deliberately.
4. **Add a "specificity test"** instruction: "Every sentence must reference something specific to THIS company or THIS candidate. If a sentence could apply to any job or any candidate, cut it."

---

## 8. Gaps in Our Current Prompts

### CV Prompt Gaps

| Gap | Current State | What Research Says | Priority |
|-----|--------------|-------------------|----------|
| **No explicit job title matching** | Prompt says "mirror keywords" generally | Job title match = 10.6x higher interview rate | HIGH |
| **No keyword extraction instruction** | "Mirror keywords naturally" is vague | LLM should be told to extract top skills from JD and ensure each appears | HIGH |
| **No DOCX output** | PDF only | DOCX is the safest ATS format | HIGH |
| **No language detection** | English only | Quebec market requires French CVs for French postings | HIGH |
| **Summary too short/generic** | "Exactly 2 sentences" | Summaries with quantified achievements get 340% more callbacks; both sentences need metrics | MEDIUM |
| **No anti-AI-detection guidance** | Not addressed | 67% of hiring managers claim to detect AI; need precise numbers, varied structure | MEDIUM |
| **Length guidance too vague** | "Aim for 1-2 pages" | For 10+ years, lean toward 2 full pages | MEDIUM |
| **No section heading guidance** | Not specified | Standard headings ("Work Experience", "Skills") are critical for ATS parsing | LOW |
| **No contact placement guidance** | Handled by template | Template puts contact in header band -- 25% of ATS skip headers | LOW |
| **CAR not explicitly named** | "Achievement format" is mentioned | CAR is the standard framework name; explicit instruction improves consistency | LOW |

### Letter Prompt Gaps

| Gap | Current State | What Research Says | Priority |
|-----|--------------|-------------------|----------|
| **Too short** | 150 words max | 250-400 words is the research consensus; 150 signals low effort | HIGH |
| **No pain-point angle** | Hook + Proof + Close | Pain-point formula is most effective for senior roles | HIGH |
| **No specific-details mandate** | "Be specific" is implied | Every sentence must reference something specific to THIS company | MEDIUM |
| **No anti-AI-detection guidance** | "No corporate speak" is a start | Need explicit ban on AI-sounding phrases, mandate varied sentence length | MEDIUM |
| **No language matching** | English only | Must match job posting language | HIGH |
| **No company research prompt** | "Why this company excites" without guidance | HBR recommends demonstrating knowledge of company challenges | MEDIUM |
| **Technology mention rule is too strict** | "DO NOT mention specific technologies unless JD names them" | For tech roles like Applied AI Engineer, technologies ARE the proof | LOW |

### Rendering/Format Gaps

| Gap | Current State | What Research Says | Priority |
|-----|--------------|-------------------|----------|
| **No DOCX output** | PDF only via WeasyPrint | DOCX is safest for ATS; PDF for human review | HIGH |
| **Custom bullet character** | Uses "▸" via CSS | Standard bullets are safer for ATS text extraction | MEDIUM |
| **Skill pills layout** | Inline-block spans with CSS | Could confuse ATS parsers; plain comma-separated is safer in DOCX | MEDIUM |
| **Header band** | Contact info in styled div | 25% of ATS fail to parse header areas | MEDIUM |
| **No ATS-friendly plain text fallback** | Not available | Some application portals strip all formatting | LOW |

---

## 9. Recommended Changes

### Prompt Changes: CV System Prompt

#### Change 1: Add explicit job title matching instruction (HIGH)

Add after the "Professional Title" section:

```
## Job Title Matching
Include the EXACT job title from the target posting at least once in the resume —
either as a secondary title line, in the summary, or as a header for the most
relevant experience entry. Candidates whose resume contains the exact target job
title have a 10.6x higher interview rate (Jobscan 2025).
```

#### Change 2: Replace vague keyword instruction with explicit extraction (HIGH)

Replace the current ATS Optimization section:

```
## ATS Optimization
1. Extract the 8-10 most important skills/technologies from the job description.
2. Ensure EACH of these appears at least once in the resume, preferably embedded
   in an achievement bullet (not just the skills list).
3. Use the EXACT phrasing from the job description — not synonyms — when the
   candidate genuinely has that skill. ATS does not always recognize synonyms.
4. Target a 65-80% keyword match rate with the job description.
5. Do not keyword-stuff. Each keyword should appear in a natural, contextual sentence.
```

#### Change 3: Strengthen the summary instruction (MEDIUM)

Replace the current Professional Summary section:

```
## Professional Summary
Write exactly 2 sentences. Both sentences MUST contain at least one quantified
claim (metric, scale, or scope number).
- Sentence 1: years of experience + primary domain + a headline achievement
  (e.g. "12 years building cloud-native systems, most recently leading a
  platform serving 2M daily users").
- Sentence 2: the specific value proposition for THIS role, with a proof point
  (e.g. "Combines deep Kubernetes expertise with hands-on ML deployment
  experience, having reduced inference latency 40% across production pipelines").
- No filler, no first-person pronouns, no generic claims without evidence.
```

#### Change 4: Add anti-AI-detection guidance (MEDIUM)

Add a new section:

```
## Authenticity
- Use precise, non-round numbers for metrics (say "37%" not "35%", say "$118K"
  not "$120K") — precise numbers signal real data, not fabrication.
- Vary sentence length: mix short punchy fragments with longer descriptive
  sentences.
- NEVER use these phrases: "proven track record", "results-oriented",
  "detail-oriented", "team player", "passionate about", "leveraged",
  "synergistic", "best-in-class", "cutting-edge", "spearheaded"
  (overused to the point of being an AI signal).
- Every bullet must be specific enough that it could NOT describe a different
  person's experience.
```

Note: "spearheaded" is currently in our recommended action verbs list. Remove it and replace with more distinctive alternatives like "Pioneered", "Initiated", "Championed".

#### Change 5: Lean toward 2 pages for experienced candidates (MEDIUM)

Replace:
```
- Aim for 1-2 pages of content.
```

With:
```
- For candidates with 8+ years of experience, produce a FULL 2-page resume.
  Do not compress into 1 page — it undersells the candidate. For candidates
  with less than 5 years, aim for 1 page.
```

#### Change 6: Explicitly name CAR format (LOW)

Replace:
```
- Transform every bullet into achievement format: strong action verb + what
was done + measurable impact.
```

With:
```
- Transform every bullet into CAR format (Challenge → Action → Result):
  Start with a strong action verb, state what challenge was addressed or
  what was built/changed, end with a measurable result or quantified scope.
  Example: "Reduced deployment failures by 73% by implementing automated
  canary releases across 8 production services."
```

### Prompt Changes: Letter System Prompt

#### Change 7: Increase word count target (HIGH)

Replace:
```
## Structure (3 short paragraphs, 150 words max total)
```

With:
```
## Structure (3 paragraphs, 200-300 words total)
```

This gives enough room to be substantive without padding. Still shorter than the 250-400 industry standard, but aligned with the "punchy, no-fluff" voice we want.

#### Change 8: Add pain-point angle to the hook paragraph (HIGH)

Replace:
```
Paragraph 1: Hook — why this specific company/role excites the candidate. \
Be specific and genuine, not generic flattery.
```

With:
```
Paragraph 1: Hook — identify a specific challenge, goal, or initiative at
this company (from the job description, company news, or industry context)
and state why solving it excites the candidate. This is NOT generic flattery
("I admire your company's innovation") — it's demonstrating you understand
what they need and why you want to help.
```

#### Change 9: Relax the technology ban for tech roles (LOW)

Replace:
```
- DO NOT mention specific technologies, languages, or tools UNLESS the job \
description explicitly names them.
```

With:
```
- Mention specific technologies ONLY when they are named in the job
description OR when they are central to proving a claim (e.g., "I built
a RAG pipeline using LangChain that cut support ticket resolution time
by 60%"). Never list technologies for their own sake — only as proof of
capability.
```

#### Change 10: Add anti-AI-detection guidance for letters (MEDIUM)

Add to the Rules section:

```
- NEVER use: "I am excited to", "I believe I would be a great fit",
  "I am confident that", "meaningful contribution", "proven track record",
  "results-driven". These are AI red flags.
- Every sentence must pass the swap test: if you can replace the company
  name with a competitor and the sentence still works, rewrite it.
- Use at least one precise metric or specific detail in the proof paragraph.
- Vary sentence length deliberately — not every sentence should be the
  same structure.
```

### Rendering/Architecture Changes

#### Change 11: Add DOCX output (HIGH)

Add a DOCX renderer alongside the current PDF renderer. Use `python-docx` to generate a clean, single-column, ATS-optimized Word document. This should be the primary format for ATS submission; the PDF serves as the polished human-readable version.

DOCX formatting rules:
- Single-column layout
- Standard section headings (use Word heading styles so ATS recognizes structure)
- Standard bullet characters
- Contact info in the document body (not in Word headers/footers)
- No tables, text boxes, or images
- Font: Calibri 10-11pt

#### Change 12: Add language detection and French generation (HIGH)

For the Quebec market, implement:

1. Detect the job posting language (simple heuristic: check for French keywords in the job description, or expose as a config option).
2. When the posting is in French, generate assets in French. This means either French system prompts or a language directive in the existing prompt.
3. Always generate the Languages section prominently regardless of output language.

#### Change 13: Improve ATS compatibility of current PDF template (MEDIUM)

- Replace the `▸` custom bullet with a standard bullet character or a simple dash.
- Test whether the colored header band (`<div class="header">`) extracts cleanly when the PDF is copy-pasted to plain text. If not, restructure.
- Consider adding a plain-text extraction test to the test suite: render a CV to PDF, extract text with a PDF library (e.g., `pdfplumber`), and verify all sections are present and in order.

#### Change 14: Languages section placement (LOW)

For Quebec-market CVs, move the Languages section higher -- after Skills, before Experience. Bilingualism is a key differentiator in Montreal and should not be buried at the bottom of page 2.

---

## Summary of Priorities

### Must-do (HIGH priority)

1. **Increase cover letter word count** from 150 to 200-300 words
2. **Add explicit job title matching** instruction to CV prompt
3. **Replace vague keyword instruction** with explicit extraction steps
4. **Add pain-point angle** to cover letter hook paragraph
5. **Add DOCX output** as primary ATS format
6. **Add French language generation** for Quebec market

### Should-do (MEDIUM priority)

7. **Strengthen summary instruction** to require quantified claims in both sentences
8. **Add anti-AI-detection guidance** to both CV and letter prompts
9. **Lean toward 2 full pages** for experienced candidates
10. **Improve PDF template** ATS compatibility (bullets, header band)
11. **Move Languages section higher** for Quebec CVs

### Nice-to-have (LOW priority)

12. **Explicitly name CAR format** in achievement bullet instructions
13. **Relax technology ban** in cover letters for tech roles
14. **Add plain-text extraction test** for ATS validation
