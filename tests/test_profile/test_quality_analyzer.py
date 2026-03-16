"""Tests for profile highlight quality analysis."""

from __future__ import annotations

from emplaiyed.core.models import Employment, Profile
from emplaiyed.profile.quality_analyzer import analyze_highlight_quality


def _profile_with_highlights(highlights: list[str]) -> Profile:
    """Helper to create a profile with one employment entry."""
    return Profile(
        name="Test User",
        email="test@example.com",
        employment_history=[
            Employment(
                company="Acme Corp",
                title="Senior Engineer",
                highlights=highlights,
            ),
        ],
    )


class TestAnalyzeHighlightQuality:
    def test_achievement_highlights_detected(self):
        profile = _profile_with_highlights([
            "Reduced deployment time by 60%",
            "Saved $200,000 annually through automation",
            "Led a team of 15 engineers",
        ])
        results = analyze_highlight_quality(profile)
        assert len(results) == 1
        assert len(results[0].strong_highlights) == 3
        assert len(results[0].weak_highlights) == 0

    def test_duty_focused_highlights_detected(self):
        profile = _profile_with_highlights([
            "Manage a team of developers",
            "Responsible for cloud infrastructure",
            "Maintain CI/CD pipelines",
        ])
        results = analyze_highlight_quality(profile)
        assert len(results) == 1
        assert len(results[0].weak_highlights) == 3
        assert len(results[0].strong_highlights) == 0

    def test_mixed_highlights(self):
        profile = _profile_with_highlights([
            "Manage a team of developers",
            "Reduced costs by 40% through cloud migration",
            "Responsible for deployment pipeline",
        ])
        results = analyze_highlight_quality(profile)
        assert len(results) == 1
        assert len(results[0].weak_highlights) == 2
        assert len(results[0].strong_highlights) == 1

    def test_no_highlights_skipped(self):
        profile = Profile(
            name="Test User",
            email="test@example.com",
            employment_history=[
                Employment(company="Acme", title="Dev", highlights=[]),
            ],
        )
        results = analyze_highlight_quality(profile)
        assert len(results) == 0

    def test_no_employment_returns_empty(self):
        profile = Profile(name="Test User", email="test@example.com")
        results = analyze_highlight_quality(profile)
        assert results == []

    def test_multiple_employers(self):
        profile = Profile(
            name="Test User",
            email="test@example.com",
            employment_history=[
                Employment(
                    company="Acme",
                    title="Dev",
                    highlights=["Manage builds"],
                ),
                Employment(
                    company="BigCo",
                    title="Lead",
                    highlights=["Reduced latency by 50%"],
                ),
            ],
        )
        results = analyze_highlight_quality(profile)
        assert len(results) == 2
        assert results[0].company == "Acme"
        assert len(results[0].weak_highlights) == 1
        assert results[1].company == "BigCo"
        assert len(results[1].strong_highlights) == 1

    def test_action_verb_without_metric_not_flagged(self):
        """Highlights with action verbs (not duty verbs) that lack metrics
        are not flagged as weak — they're acceptable."""
        profile = _profile_with_highlights([
            "Architected a new microservices platform",
            "Delivered the project ahead of schedule",
        ])
        results = analyze_highlight_quality(profile)
        assert len(results) == 1
        assert len(results[0].weak_highlights) == 0
        assert len(results[0].strong_highlights) == 0

    def test_duty_verb_with_metrics_not_weak(self):
        """A duty verb + metrics = not weak (the metric makes it acceptable)."""
        profile = _profile_with_highlights([
            "Managed a team of 15 engineers across 3 time zones",
        ])
        results = analyze_highlight_quality(profile)
        assert len(results) == 1
        assert len(results[0].weak_highlights) == 0
        assert len(results[0].strong_highlights) == 1
