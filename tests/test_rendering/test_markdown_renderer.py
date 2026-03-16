"""Tests for markdown rendering of CV and letter."""

from __future__ import annotations

from pathlib import Path

import pytest

from emplaiyed.generation.cv_generator import (
    CVCertification,
    CVEducation,
    CVExperience,
    GeneratedCV,
    SkillCategory,
)
from emplaiyed.generation.letter_generator import GeneratedLetter
from emplaiyed.rendering.markdown_renderer import (
    render_cv_markdown,
    render_letter_markdown,
    write_cv_markdown,
    write_letter_markdown,
)


def _sample_cv() -> GeneratedCV:
    return GeneratedCV(
        name="Alice Test",
        email="alice@example.com",
        phone="+1-555-0000",
        location="Montreal, QC",
        professional_title="Senior Cloud Architect",
        summary="Seasoned cloud architect with 10+ years of experience.",
        skill_categories=[
            SkillCategory(category="Cloud", skills=["AWS", "GCP"]),
            SkillCategory(category="Languages", skills=["Python", "Go"]),
        ],
        experience=[
            CVExperience(
                company="Acme Corp",
                title="Lead Developer",
                start_date="2020-01",
                end_date="Present",
                description="Led cloud migration.",
                highlights=["Reduced costs by 40%", "Shipped v2"],
            ),
        ],
        education=[
            CVEducation(
                institution="Université Laval",
                degree="M.Sc.",
                field="Computer Science",
                start_date="2010",
                end_date="2012",
            ),
        ],
        certifications=[
            CVCertification(
                name="AWS Solutions Architect", issuer="Amazon", date="2023"
            ),
        ],
        languages=["French (Native)", "English (Fluent)"],
    )


def _sample_letter() -> GeneratedLetter:
    return GeneratedLetter(
        greeting="Dear Hiring Manager,",
        hook="I am writing to express my interest in the Cloud Architect position.",
        proof="With 10 years of experience in cloud infrastructure...",
        close="I would love to discuss how I can contribute.",
        closing="Sincerely,",
        signature_name="Alice Test",
    )


class TestRenderCVMarkdown:
    def test_includes_all_cv_sections(self):
        md = render_cv_markdown(_sample_cv())
        for expected in [
            "# Alice Test",
            "Senior Cloud Architect",
            "alice@example.com",
            "+1-555-0000",
            "## Summary",
            "10+ years",
            "**Cloud:**",
            "AWS",
            "**Languages:**",
            "Python",
            "Acme Corp",
            "Lead Developer",
            "Reduced costs by 40%",
            "Université Laval",
            "M.Sc.",
            "Computer Science",
            "AWS Solutions Architect",
            "Amazon",
            "French (Native)",
        ]:
            assert expected in md, f"Expected '{expected}' in rendered CV markdown"

    def test_empty_optional_sections(self):
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            summary="A developer.",
            skill_categories=[SkillCategory(category="Programming", skills=["Go"])],
            experience=[],
            education=[],
        )
        md = render_cv_markdown(cv)
        assert "# Bob" in md
        assert "Certifications" not in md
        assert "## Languages" not in md
        assert "## Experience" not in md


class TestRenderLetterMarkdown:
    def test_includes_all_letter_sections(self):
        md = render_letter_markdown(_sample_letter())
        for expected in [
            "Dear Hiring Manager,",
            "Cloud Architect position",
            "Sincerely,",
            "Alice Test",
        ]:
            assert expected in md, f"Expected '{expected}' in rendered letter markdown"


class TestWriteFiles:
    @pytest.mark.parametrize(
        "write_fn, make_data, filename, expected_content",
        [
            (write_cv_markdown, _sample_cv, "cv.md", "# Alice Test"),
            (
                write_letter_markdown,
                _sample_letter,
                "letter.md",
                "Dear Hiring Manager,",
            ),
        ],
        ids=["cv", "letter"],
    )
    def test_write_markdown_file(
        self, tmp_path, write_fn, make_data, filename, expected_content
    ):
        path = tmp_path / filename
        write_fn(make_data(), path)
        assert path.exists()
        assert expected_content in path.read_text()

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "cv.md"
        write_cv_markdown(_sample_cv(), path)
        assert path.exists()
