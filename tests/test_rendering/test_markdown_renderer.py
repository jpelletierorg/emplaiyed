"""Tests for markdown rendering of CV and letter."""

from __future__ import annotations

from pathlib import Path

from emplaiyed.generation.cv_generator import CVExperience, GeneratedCV
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
        skills=["Python", "AWS", "Docker", "Kubernetes"],
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
        education=["M.Sc. Computer Science, Université Laval"],
        certifications=["AWS Solutions Architect (2023)"],
        languages=["French (Native)", "English (Fluent)"],
    )


def _sample_letter() -> GeneratedLetter:
    return GeneratedLetter(
        greeting="Dear Hiring Manager,",
        body="I am writing to express my interest in the Cloud Architect position. "
             "With 10 years of experience in cloud infrastructure...",
        closing="Sincerely,",
        signature_name="Alice Test",
    )


class TestRenderCVMarkdown:
    def test_includes_name_as_heading(self):
        md = render_cv_markdown(_sample_cv())
        assert "# Alice Test" in md

    def test_includes_professional_title(self):
        md = render_cv_markdown(_sample_cv())
        assert "Senior Cloud Architect" in md

    def test_includes_contact_info(self):
        md = render_cv_markdown(_sample_cv())
        assert "alice@example.com" in md
        assert "+1-555-0000" in md

    def test_includes_skills(self):
        md = render_cv_markdown(_sample_cv())
        assert "Python" in md
        assert "AWS" in md

    def test_includes_experience(self):
        md = render_cv_markdown(_sample_cv())
        assert "Acme Corp" in md
        assert "Lead Developer" in md
        assert "Reduced costs by 40%" in md

    def test_includes_education(self):
        md = render_cv_markdown(_sample_cv())
        assert "Université Laval" in md

    def test_includes_certifications(self):
        md = render_cv_markdown(_sample_cv())
        assert "AWS Solutions Architect" in md

    def test_includes_languages(self):
        md = render_cv_markdown(_sample_cv())
        assert "French (Native)" in md

    def test_empty_optional_sections(self):
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            skills=["Go"],
            experience=[],
            education=[],
        )
        md = render_cv_markdown(cv)
        assert "# Bob" in md
        assert "Certifications" not in md
        assert "Languages" not in md


class TestRenderLetterMarkdown:
    def test_includes_greeting(self):
        md = render_letter_markdown(_sample_letter())
        assert "Dear Hiring Manager," in md

    def test_includes_body(self):
        md = render_letter_markdown(_sample_letter())
        assert "Cloud Architect position" in md

    def test_includes_closing(self):
        md = render_letter_markdown(_sample_letter())
        assert "Sincerely," in md

    def test_includes_signature(self):
        md = render_letter_markdown(_sample_letter())
        assert "Alice Test" in md


class TestWriteFiles:
    def test_write_cv_markdown(self, tmp_path: Path):
        path = tmp_path / "cv.md"
        write_cv_markdown(_sample_cv(), path)
        assert path.exists()
        content = path.read_text()
        assert "# Alice Test" in content

    def test_write_letter_markdown(self, tmp_path: Path):
        path = tmp_path / "letter.md"
        write_letter_markdown(_sample_letter(), path)
        assert path.exists()
        content = path.read_text()
        assert "Dear Hiring Manager," in content

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "cv.md"
        write_cv_markdown(_sample_cv(), path)
        assert path.exists()
