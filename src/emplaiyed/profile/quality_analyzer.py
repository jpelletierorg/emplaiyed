"""Heuristic quality analysis of profile employment highlights.

Identifies duty-focused highlights (no metrics/achievements) vs.
achievement-focused highlights (contain numbers, percentages, concrete outcomes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from emplaiyed.core.models import Profile

# Patterns that indicate quantified achievements
_METRIC_PATTERNS = [
    re.compile(r"\d+%"),          # percentages
    re.compile(r"\$[\d,]+"),      # dollar amounts
    re.compile(r"\d+[xX]\b"),     # multipliers like "3x"
    re.compile(r"\b\d{2,}\b"),    # numbers >= 10 (team sizes, counts, etc.)
]

# Verbs that typically start duty-focused (non-achievement) highlights
_DUTY_VERBS = {
    "manage", "maintain", "responsible", "support", "assist",
    "coordinate", "participate", "handle", "oversee", "ensure",
    "perform", "attend", "provide", "facilitate", "organize",
}


def _has_metrics(text: str) -> bool:
    """Check if text contains quantified outcomes."""
    return any(p.search(text) for p in _METRIC_PATTERNS)


def _starts_with_duty_verb(text: str) -> bool:
    """Check if text starts with a duty-focused verb."""
    first_word = text.strip().split()[0].lower().rstrip("s,.:;") if text.strip() else ""
    return first_word in _DUTY_VERBS


def _is_achievement(text: str) -> bool:
    """Heuristic: a highlight is an achievement if it has metrics."""
    return _has_metrics(text)


def _is_duty_focused(text: str) -> bool:
    """Heuristic: a highlight is duty-focused if it starts with a duty verb
    and has no metrics."""
    return _starts_with_duty_verb(text) and not _has_metrics(text)


@dataclass
class HighlightQuality:
    employment_index: int
    company: str
    title: str
    weak_highlights: list[int] = field(default_factory=list)
    strong_highlights: list[int] = field(default_factory=list)


def analyze_highlight_quality(profile: Profile) -> list[HighlightQuality]:
    """Analyze employment highlights for achievement vs. duty focus.

    Returns a list of HighlightQuality, one per employment entry that has
    highlights. Entries with no highlights are skipped.
    """
    results: list[HighlightQuality] = []
    for idx, emp in enumerate(profile.employment_history):
        if not emp.highlights:
            continue
        hq = HighlightQuality(
            employment_index=idx,
            company=emp.company,
            title=emp.title,
        )
        for hi, text in enumerate(emp.highlights):
            if _is_achievement(text):
                hq.strong_highlights.append(hi)
            elif _is_duty_focused(text):
                hq.weak_highlights.append(hi)
            # Highlights that are neither (action verbs without metrics but
            # not duty verbs) are considered acceptable — not flagged.
        results.append(hq)
    return results
