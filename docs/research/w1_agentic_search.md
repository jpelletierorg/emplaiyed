# Week 1 Research: Agentic Job Search with Pydantic AI

**Date**: 2026-02-16
**Pydantic AI version**: 1.58.0 (installed in project)

---

## 1. Problem Statement

The current `emplaiyed sources scan` command does keyword-based scraping: it takes a list of keywords (derived from profile target roles + top skills), hits one source at a time, and returns whatever matches. The user must run it repeatedly with different keywords to get diverse results.

We want an **agentic search** where a Pydantic AI agent autonomously:
- Reasons about the profile to generate diverse search queries
- Calls `search_jobs` as a tool, inspecting results after each call
- Adapts strategy based on what it found (sparse results -> broaden; lots of duplicates -> try different angle)
- Stops when it has 10+ relevant, deduplicated opportunities
- Returns a structured result

---

## 2. Pydantic AI Agent Patterns for Autonomous Search

### 2.1 The Core Pattern: Agent with Tools

Pydantic AI agents call tools in a loop. The agent receives a prompt, decides to call one or more tools, receives the tool results, then decides whether to call more tools or produce a final output. This loop is managed internally by the framework -- you do not write the loop yourself.

Here is the pattern mapped to our codebase:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.sources.base import BaseSource, SearchQuery

logger = logging.getLogger(__name__)


# -- Dependencies: everything the agent's tools need access to --

@dataclass
class SearchDeps:
    """Runtime dependencies injected into the agent."""
    profile: Profile
    sources: dict[str, BaseSource]  # e.g. {"jobbank": JobBankSource(), ...}
    found: list[Opportunity]        # accumulator, mutated by tools
    seen_keys: set[tuple[str, str, str]]  # (company, title, source) dedup set
    queries_tried: list[str]        # track what we already searched


# -- Structured output --

class SearchResult(BaseModel):
    """Final output the agent must produce."""
    opportunities: list[Opportunity]
    queries_used: list[str] = Field(default_factory=list)
    summary: str  # brief explanation of what the agent did


# -- The Agent --

search_agent = Agent(
    # Model is set at construction or overridden at run time
    "openrouter:anthropic/claude-haiku-4.5",
    deps_type=SearchDeps,
    output_type=SearchResult,
    instructions=(
        "You are a job search agent. Your goal is to find at least 10 relevant "
        "job opportunities for the user by searching multiple job sources with "
        "diverse queries.\n\n"
        "Strategy:\n"
        "1. Start by analyzing the user's profile (skills, target roles, location).\n"
        "2. Generate 3-5 diverse search queries covering: exact target roles, "
        "related roles, skill-based queries, and industry-based queries.\n"
        "3. Call search_jobs for each query. After each call, review results.\n"
        "4. If a query returns few results (<3), try a broader or alternative query.\n"
        "5. Stop when you have 10+ unique, relevant opportunities.\n"
        "6. Return ALL found opportunities with a summary of your search strategy.\n\n"
        "Do NOT return opportunities that are clearly irrelevant to the profile."
    ),
)
```

### 2.2 Defining the Search Tool

The tool is what bridges the agent to our existing `BaseSource` infrastructure. The agent calls it with keywords, location, and source name. The tool calls `source.scrape()` and returns results.

```python
@search_agent.tool
async def search_jobs(
    ctx: RunContext[SearchDeps],
    keywords: list[str],
    source_name: str,
    location: str | None = None,
) -> str:
    """Search a job source for opportunities matching the given keywords.

    Args:
        keywords: Search terms, e.g. ["cloud architect", "AWS"].
        source_name: Which source to search. Available: "jobbank".
        location: Optional location filter, e.g. "Montreal, QC".

    Returns:
        A summary of results found, including count and titles.
    """
    deps = ctx.deps
    source = deps.sources.get(source_name)
    if source is None:
        return f"Unknown source '{source_name}'. Available: {list(deps.sources.keys())}"

    query = SearchQuery(
        keywords=keywords,
        location=location,
        max_results=25,
    )

    query_desc = f"{', '.join(keywords)} on {source_name}"
    deps.queries_tried.append(query_desc)

    try:
        results = await source.scrape(query)
    except NotImplementedError:
        return f"Source '{source_name}' is not yet implemented."
    except Exception as exc:
        logger.warning("Search failed: %s", exc)
        return f"Search failed: {exc}"

    # Dedup against what we already found
    new_opps: list[Opportunity] = []
    for opp in results:
        key = (opp.company.lower(), opp.title.lower(), opp.source.lower())
        if key not in deps.seen_keys:
            deps.seen_keys.add(key)
            deps.found.append(opp)
            new_opps.append(opp)

    # Return a summary for the agent to reason about
    if not new_opps:
        return f"Search '{query_desc}': 0 new results (all duplicates or empty)."

    titles = [f"- {o.title} at {o.company}" for o in new_opps[:10]]
    summary = (
        f"Search '{query_desc}': {len(new_opps)} new results "
        f"({len(deps.found)} total unique so far).\n"
        + "\n".join(titles)
    )
    if len(new_opps) > 10:
        summary += f"\n... and {len(new_opps) - 10} more"

    return summary
```

Key design decisions:

1. **The tool returns a string summary, not the raw `Opportunity` objects.** The agent does not need to see full descriptions in its context window. It needs enough to reason about coverage and decide what to search next. The actual `Opportunity` objects accumulate in `deps.found`.

2. **Deduplication happens in the tool**, not in the agent's reasoning. This is deterministic logic that should not consume tokens.

3. **The tool tracks queries tried** so the agent can see what it already searched and avoid repeating itself.

### 2.3 Running the Agent

```python
async def agentic_search(
    profile: Profile,
    sources: dict[str, BaseSource],
    *,
    _model_override: Model | None = None,
) -> SearchResult:
    """Run the agentic search loop."""
    deps = SearchDeps(
        profile=profile,
        sources=sources,
        found=[],
        seen_keys=set(),
        queries_tried=[],
    )

    # Build the user prompt from the profile
    prompt = _build_search_prompt(profile)

    result = await search_agent.run(
        prompt,
        deps=deps,
        usage_limits=UsageLimits(
            request_limit=15,       # max LLM round-trips
            tool_calls_limit=20,    # max total tool invocations
        ),
        model=_model_override,  # for tests: pass TestModel()
    )

    # The agent returns SearchResult, but we ensure the opportunities
    # list matches what was actually accumulated (the agent might
    # hallucinate or omit some)
    output = result.output
    output.opportunities = deps.found
    output.queries_used = deps.queries_tried
    return output


def _build_search_prompt(profile: Profile) -> str:
    """Build the initial prompt describing the user's profile."""
    parts = [f"Find jobs for this candidate:\n"]
    parts.append(f"Name: {profile.name}")

    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills[:15])}")

    if profile.aspirations:
        a = profile.aspirations
        if a.target_roles:
            parts.append(f"Target roles: {', '.join(a.target_roles)}")
        if a.geographic_preferences:
            parts.append(f"Preferred locations: {', '.join(a.geographic_preferences)}")
        if a.work_arrangement:
            parts.append(f"Work arrangement: {', '.join(a.work_arrangement)}")
        if a.salary_minimum or a.salary_target:
            parts.append(
                f"Salary: min ${a.salary_minimum or 0:,}, target ${a.salary_target or 0:,}"
            )
        if a.target_industries:
            parts.append(f"Target industries: {', '.join(a.target_industries)}")

    if profile.employment_history:
        recent = profile.employment_history[0]
        parts.append(f"Most recent role: {recent.title} at {recent.company}")

    if profile.certifications:
        cert_names = [c.name for c in profile.certifications[:5]]
        parts.append(f"Certifications: {', '.join(cert_names)}")

    return "\n".join(parts)
```

### 2.4 How the Agent Loop Works Internally

When you call `agent.run()`, Pydantic AI executes this loop:

```
1. Send system prompt + user prompt to LLM
2. LLM responds with either:
   a. Tool calls -> execute tools, send results back to LLM, goto 2
   b. Final output (matching output_type) -> return
3. Repeat until output or limits exceeded
```

The agent autonomously decides:
- Which tools to call and with what arguments
- Whether to call multiple tools in parallel (Pydantic AI supports this)
- When it has enough information to produce the final SearchResult

The `UsageLimits` are the safety valve. `request_limit=15` means at most 15 LLM round-trips; `tool_calls_limit=20` means at most 20 individual tool invocations across all round-trips.

### 2.5 Testing with TestModel

The existing codebase uses `_model_override` with `TestModel()` for unit tests. The same pattern works for the agentic search:

```python
from pydantic_ai.models.test import TestModel

async def test_agentic_search_calls_tools():
    """Verify the agent calls search_jobs and produces output."""
    model = TestModel()
    # TestModel will call each registered tool once and produce
    # a default SearchResult output. For more control, use
    # FunctionModel to script specific tool call sequences.
    result = await agentic_search(
        profile=make_test_profile(),
        sources={"jobbank": FakeJobBankSource()},
        _model_override=model,
    )
    assert isinstance(result, SearchResult)
```

For more realistic tests, `FunctionModel` lets you script the exact sequence of tool calls and responses the model would make.

---

## 3. Multi-Pass Search Strategies

The agent's system prompt guides its search strategy, but here are the concrete query generation patterns it should use:

### 3.1 Query Diversity Matrix

Given Jonathan's profile as an example:

| Strategy | Example Queries | Rationale |
|----------|----------------|-----------|
| **Exact target role** | `["Applied AI Engineer"]` | Direct match to aspirations |
| **Role synonyms** | `["Machine Learning Engineer"]`, `["AI Developer"]` | Same role, different titles |
| **Adjacent roles** | `["Cloud Architect"]`, `["DevOps Engineer"]`, `["Platform Engineer"]` | Leverage cloud/infra background |
| **Skill-based** | `["Python AWS"]`, `["Terraform Docker"]` | Match skills regardless of title |
| **Seniority variations** | `["Senior Software Engineer"]`, `["Lead Engineer"]`, `["Staff Engineer"]` | Different seniority framings |
| **Industry-based** | `["fintech engineer"]`, `["SaaS platform"]` | Target specific industries |
| **Bilingual advantage** | `["ingenieur logiciel"]`, `["developpeur Python"]` | French-language postings (Quebec) |

### 3.2 Adaptive Strategy

The agent should adapt based on results:

- **Sparse results** (< 3 from a query): Broaden keywords, drop location constraint, try synonyms
- **Too many irrelevant results**: Add qualifying terms ("senior", specific tech), narrow location
- **All duplicates from prior queries**: Switch to a completely different angle (skill-based vs role-based)
- **Good results from one source**: Try the same query on other sources

This adaptation is handled by the LLM's reasoning, not by code. The system prompt instructs the agent to do this, and the tool result summaries give it the information to reason about.

### 3.3 Location Expansion

Current sources (Job Bank) support province-level filtering. The agent should:
1. Start with the user's preferred location (Montreal)
2. If results are thin, expand to province (Quebec)
3. If still thin, drop location entirely (all of Canada)
4. For remote-friendly users, try queries without location constraint

---

## 4. Quality Filtering

### 4.1 In-Agent vs Post-Agent Filtering

There are two levels of filtering:

**In-agent (during search)**: The agent sees tool result summaries and can decide to exclude obviously irrelevant results. However, this is coarse -- the agent only sees titles and company names, not full descriptions.

**Post-agent (after search)**: The existing `score_opportunities()` function does deep relevance scoring with full descriptions. This is where real quality filtering happens.

**Recommendation**: Keep quality filtering in the post-agent scoring step. The agentic search should cast a wide net; the scorer filters. This is cleaner separation of concerns and avoids spending agent tokens on detailed relevance analysis that the scorer already does.

### 4.2 Lightweight Pre-filtering in the Tool

The tool can do basic pre-filtering without LLM involvement:

```python
# Inside search_jobs tool, before adding to deps.found:
def _basic_filter(opp: Opportunity, profile: Profile) -> bool:
    """Quick relevance check without LLM. Rejects obvious mismatches."""
    title_lower = opp.title.lower()

    # Reject if title contains obvious seniority mismatch
    junior_terms = ["intern", "co-op", "junior", "entry level", "stage"]
    if any(term in title_lower for term in junior_terms):
        return False

    # Reject if salary is below minimum (when both are known)
    if (
        profile.aspirations
        and profile.aspirations.salary_minimum
        and opp.salary_max
        and opp.salary_max < profile.aspirations.salary_minimum
    ):
        return False

    return True
```

This saves the scorer from wasting LLM calls on obviously bad matches.

### 4.3 The Full Pipeline

```
Profile -> Agentic Search (wide net, basic filter) -> Scorer (deep LLM filter) -> Ranked list
```

---

## 5. Practical Considerations

### 5.1 Token Costs

Using OpenRouter pricing (as of Feb 2026):

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|----------------------|
| `anthropic/claude-haiku-4.5` | ~$1.00 | ~$5.00 |
| `anthropic/claude-sonnet-4-5` | ~$3.00 | ~$15.00 |

**Cost estimate for one agentic search run with Haiku 4.5:**

| Step | Tokens (approx) | Cost |
|------|-----------------|------|
| System prompt + profile | ~800 input | negligible |
| Per tool call round-trip (x8 avg) | ~500 input + ~200 output each | ~$0.004 + $0.008 = ~$0.01 |
| Tool result context growth | ~2000 cumulative input by end | ~$0.002 |
| Final output generation | ~300 output | ~$0.0015 |
| **Total agent** | ~6000 input, ~2000 output | **~$0.02** |

Then scoring (existing system, runs separately):

| Step | Tokens (approx) | Cost |
|------|-----------------|------|
| Score 15 opportunities (Haiku) | ~1500 input + ~200 output each | ~$0.02 + $0.015 = ~$0.035 |
| **Total scoring** | ~22500 input, ~3000 output | **~$0.04** |

**Total cost per search run: approximately $0.05 - $0.10 with Haiku 4.5.** This is well within acceptable range for a tool that runs a few times per week.

With Sonnet, costs would be roughly 3x higher (~$0.15-$0.30 per run). Haiku is the right choice for the search agent since the reasoning required is not complex.

### 5.2 Latency

| Component | Expected Latency |
|-----------|-----------------|
| Each LLM round-trip (Haiku) | 1-3 seconds |
| Each scrape call (Job Bank) | 2-5 seconds (HTTP + parsing) |
| Agent loop (8 iterations avg) | 25-60 seconds total |
| Scoring (15 opps, concurrent) | 5-15 seconds |
| **Total end-to-end** | **30-75 seconds** |

This is acceptable for a CLI tool. The UX happy path shows `emplaiyed sources scan` as a command the user runs and waits for -- a minute is fine.

### 5.3 Rate Limiting

**OpenRouter**: 200 requests/minute on most plans. With 8-15 LLM calls per search run, this is not a concern.

**Job Bank (jobbank.gc.ca)**: No documented rate limit, but as a government site, we should be respectful. Current code makes sequential HTTP requests. With 5-8 search queries x ~25 detail page fetches each, that is 125-200 HTTP requests per run. At sequential execution, this is spread over 30-60 seconds, which should be fine. Adding a small delay (100-200ms) between requests would be prudent.

**Mitigation**: The `max_results=25` parameter on `SearchQuery` already limits how many detail pages we fetch per query. The agent can control this via the tool.

### 5.4 Error Handling

The tool should handle scraping failures gracefully and report them to the agent so it can retry with different parameters or skip that source:

```python
try:
    results = await source.scrape(query)
except Exception as exc:
    return f"Search failed for '{query_desc}': {exc}. Try different keywords or source."
```

The agent sees this as a tool result and can decide to retry, try a different source, or move on.

### 5.5 Context Window Growth

Each tool call adds to the conversation context. With 8-10 tool calls, each returning ~200-token summaries, the context grows by ~2000 tokens over the run. This is well within limits even for smaller models.

**Important**: The tool returns summaries, not full opportunity descriptions. Full descriptions (which can be 1500+ characters each) stay in `deps.found` and never enter the LLM context. This is critical for cost and context management.

---

## 6. Alternative Approaches Considered

### 6.1 Non-Agentic Multi-Query (Rejected)

Generate all queries upfront with one LLM call, then execute them all without adaptation:

```python
queries = await complete_structured(
    "Generate 8 diverse search queries for this profile...",
    output_type=QueryPlan,
)
for q in queries.queries:
    results += await source.scrape(q)
```

**Why rejected**: No adaptation. If the first 3 queries all return the same results, the remaining 5 are wasted. The agentic approach sees intermediate results and pivots.

### 6.2 Fully Autonomous with LLM-Based Filtering (Rejected)

Have the agent also score each opportunity inline:

```python
@search_agent.tool
async def evaluate_opportunity(ctx, opportunity_id: str) -> str:
    """Score how relevant this opportunity is."""
    ...
```

**Why rejected**: Expensive (extra LLM call per opportunity), duplicates what the existing scorer does, and bloats the agent's context. Keep search and scoring as separate steps.

### 6.3 Multi-Agent Delegation (Considered but Deferred)

Have a "coordinator" agent that delegates to specialized "query generator" and "result analyzer" sub-agents:

```python
@coordinator.tool
async def generate_queries(ctx, strategy: str) -> list[str]:
    result = await query_agent.run(strategy, deps=ctx.deps, usage=ctx.usage)
    return result.output
```

**Why deferred**: Over-engineered for the current scope. A single agent with one tool is simpler and sufficient. If we later add multiple sources with different APIs (Indeed, LinkedIn, etc.), or need more sophisticated query planning, multi-agent delegation becomes worthwhile.

---

## 7. Recommended Approach

### 7.1 Architecture

```
                        +------------------+
                        |  search_agent    |
                        |  (Pydantic AI)   |
                        |                  |
                        |  instructions:   |
                        |  - analyze profile|
                        |  - diverse queries|
                        |  - adapt strategy|
                        +--------+---------+
                                 |
                          calls tool
                                 |
                        +--------v---------+
                        |  search_jobs     |
                        |  (tool function) |
                        |                  |
                        |  - receives kw,  |
                        |    source, loc   |
                        |  - calls scrape()|
                        |  - dedups        |
                        |  - returns       |
                        |    summary       |
                        +--------+---------+
                                 |
                          delegates to
                                 |
                        +--------v---------+
                        |  BaseSource      |
                        |  .scrape()       |
                        |  (existing infra)|
                        +------------------+
```

### 7.2 Implementation Plan

**File**: `src/emplaiyed/sources/search_agent.py`

| Component | What | Lines (est) |
|-----------|------|-------------|
| `SearchDeps` dataclass | Dependencies for the agent | 15 |
| `SearchResult` model | Structured output | 10 |
| `search_agent` Agent | Agent definition with instructions | 20 |
| `search_jobs` tool | Tool that calls `BaseSource.scrape()` | 50 |
| `_basic_filter` | Quick relevance pre-filter | 15 |
| `agentic_search()` | Public entry point | 30 |
| `_build_search_prompt()` | Profile to prompt | 25 |
| **Total** | | **~165** |

**File**: `tests/test_sources/test_search_agent.py`

| Test | What |
|------|------|
| `test_agent_calls_search_tool` | Verify tool is called with TestModel |
| `test_deduplication` | Same opp from two queries is not doubled |
| `test_basic_filter_rejects_junior` | Pre-filter catches junior roles |
| `test_basic_filter_rejects_low_salary` | Pre-filter catches low salary |
| `test_unknown_source_handled` | Agent gets error message for bad source |
| `test_integration_real_api` | End-to-end with real LLM + real Job Bank |

**CLI integration**: Modify `sources_cmd.py` to add an `--agentic` flag or a new `emplaiyed sources search` command that uses the agent instead of the current direct-scrape approach.

### 7.3 Model Choice

Use **`anthropic/claude-haiku-4.5`** for the search agent. The reasoning required (generate diverse keywords, decide when to stop) is not complex. Haiku handles it well at 1/3 the cost of Sonnet. The scoring step (which requires deeper analysis of job descriptions) can remain on whatever model `DEFAULT_MODEL` points to.

### 7.4 Key Decisions

1. **Single agent, single tool**: Start simple. One agent with `search_jobs` as its only tool. Add tools later if needed (e.g., `get_profile_detail`, `check_company`).

2. **Tool returns summaries, not objects**: The agent sees "5 new results, including Cloud Architect at Coveo". The full `Opportunity` objects accumulate in `deps.found` outside the LLM context.

3. **Dedup in the tool, not the agent**: Deterministic logic stays in Python. The agent focuses on strategy.

4. **Post-agent scoring**: The agent finds candidates; the existing scorer ranks them. Clean separation.

5. **UsageLimits as guardrail**: `request_limit=15, tool_calls_limit=20` prevents runaway costs. A typical run will use 5-10 of each.

6. **Testable via `_model_override`**: Same pattern as all other LLM code in the codebase.

### 7.5 What This Gets Us

For Jonathan's profile, a single `emplaiyed sources search` run would:

1. Agent analyzes profile: cloud architect background, Applied AI target, Montreal area, bilingual
2. Searches "Applied AI Engineer" on jobbank -> 3 results
3. Searches "Machine Learning Engineer" on jobbank -> 5 results (2 new)
4. Searches "Cloud Architect" on jobbank -> 8 results (6 new)
5. Searches "ingenieur IA" on jobbank -> 4 results (3 new)
6. Searches "DevOps Engineer AWS" on jobbank -> 7 results (4 new)
7. Agent sees 18 unique opportunities, decides that is enough
8. Returns SearchResult with 18 opportunities and summary

Total: 7 tool calls, ~10 LLM round-trips, ~$0.03, ~45 seconds.

Then the existing scoring pipeline ranks them all, generating CVs and cover letters for the top scorers. The user reviews the console and starts outreach.

---

## Sources

- [Pydantic AI Agents documentation](https://ai.pydantic.dev/agent/)
- [Pydantic AI Function Tools](https://ai.pydantic.dev/tools/)
- [Pydantic AI Advanced Tool Features](https://ai.pydantic.dev/tools-advanced/)
- [Pydantic AI Toolsets](https://ai.pydantic.dev/toolsets/)
- [Pydantic AI Multi-Agent Patterns](https://ai.pydantic.dev/multi-agent-applications/)
- [OpenRouter Pricing](https://openrouter.ai/pricing)
- [Pydantic AI GitHub Repository](https://github.com/pydantic/pydantic-ai)
