"""Tests for HTML/PDF rendering of CV and letter."""

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
from emplaiyed.core.models import Address, Profile
from emplaiyed.generation.letter_generator import GeneratedLetter
from emplaiyed.rendering.html_renderer import (
    _format_date,
    render_cv_html,
    render_cv_pdf,
    render_letter_html,
    render_letter_pdf,
)


def _sample_cv() -> GeneratedCV:
    return GeneratedCV(
        name="Alice Test",
        email="alice@example.com",
        phone="+1-555-0000",
        location="Montreal, QC",
        professional_title="Senior Cloud Architect",
        summary="Seasoned cloud architect with 10+ years of experience designing scalable infrastructure.",
        skill_categories=[
            SkillCategory(
                category="Cloud & Infrastructure", skills=["AWS", "GCP", "Terraform"]
            ),
            SkillCategory(category="Programming", skills=["Python", "Go"]),
        ],
        experience=[
            CVExperience(
                company="Acme Corp",
                title="Lead Developer",
                start_date="2020-01",
                end_date="Present",
                description="Led cloud migration.",
                highlights=["Reduced costs by 40%"],
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
        proof="With 10 years of cloud experience, I reduced costs by 37%.",
        close="I would love to discuss this further.",
        closing="Sincerely,",
        signature_name="Alice Test",
    )


def _sample_profile() -> Profile:
    return Profile(
        name="Alice Test",
        email="alice@example.com",
        phone="+1-555-0000",
        address=Address(city="Montreal", province_state="QC"),
        linkedin="https://linkedin.com/in/alice",
        github="https://github.com/alice",
    )


# --- _format_date -----------------------------------------------------------


class TestFormatDate:
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("2021-10-15", "Oct 2021"),
            ("2021-10", "Oct 2021"),
            ("2023-01", "Jan 2023"),
            ("2021", "2021"),
            ("Present", "Present"),
            ("present", "Present"),
            ("Oct 2021", "Oct 2021"),
        ],
        ids=[
            "iso-with-day",
            "iso-without-day",
            "january",
            "year-only",
            "present",
            "present-lowercase",
            "already-formatted",
        ],
    )
    def test_valid_dates(self, input_val: str, expected: str):
        assert _format_date(input_val) == expected

    @pytest.mark.parametrize(
        "input_val, default, expected",
        [
            (None, "", ""),
            (None, "Present", "Present"),
        ],
        ids=["none-empty-default", "none-custom-default"],
    )
    def test_none_returns_default(self, input_val, default: str, expected: str):
        assert _format_date(input_val, default) == expected


# --- render_cv_html ---------------------------------------------------------


class TestRenderCVHTML:
    def test_contains_all_cv_sections(self):
        html = render_cv_html(_sample_cv())
        for expected in [
            "Alice Test",
            "10+ years",
            "Cloud &amp; Infrastructure",
            "AWS",
            "Python",
            "Acme Corp",
            "Reduced costs by 40%",
            "Universit",
            "Computer Science",
            "AWS Solutions Architect",
            "Amazon",
            "French (Native)",
            "Jan 2020",
        ]:
            assert expected in html, f"Expected '{expected}' in rendered CV HTML"

    def test_linkedin_and_github_rendered(self):
        cv = _sample_cv()
        cv.linkedin = "https://linkedin.com/in/alice"
        cv.github = "https://github.com/alice"
        html = render_cv_html(cv)
        assert "LinkedIn" in html
        assert "GitHub" in html


# --- render_cv_pdf ----------------------------------------------------------


class TestRenderCVPDF:
    def test_creates_valid_pdf(self, tmp_path: Path):
        path = tmp_path / "cv.pdf"
        render_cv_pdf(_sample_cv(), path)
        assert path.exists()
        assert path.stat().st_size > 0
        assert path.read_bytes()[:5] == b"%PDF-"

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "cv.pdf"
        render_cv_pdf(_sample_cv(), path)
        assert path.exists()

    def test_minimal_cv(self, tmp_path: Path):
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            summary="A developer.",
            skill_categories=[SkillCategory(category="Languages", skills=["Python"])],
            experience=[],
            education=[],
        )
        path = tmp_path / "minimal.pdf"
        render_cv_pdf(cv, path)
        assert path.exists()
        assert path.stat().st_size > 0


# --- render_letter_html -----------------------------------------------------


class TestRenderLetterHTML:
    def test_without_profile_no_header(self):
        html = render_letter_html(_sample_letter())
        assert 'class="header"' not in html

    def test_with_profile_contains_all_sections(self):
        html = render_letter_html(_sample_letter(), profile=_sample_profile())
        for expected in [
            'class="header"',
            "Alice Test",
            "alice@example.com",
            "Montreal",
            "LinkedIn",
            "Cloud Architect position",
            "Dear Hiring Manager",
            "Sincerely",
        ]:
            assert expected in html, f"Expected '{expected}' in rendered letter HTML"


# --- render_letter_pdf ------------------------------------------------------


class TestRenderLetterPDF:
    def test_creates_valid_pdf(self, tmp_path: Path):
        path = tmp_path / "letter.pdf"
        render_letter_pdf(_sample_letter(), path)
        assert path.exists()
        assert path.stat().st_size > 0
        assert path.read_bytes()[:5] == b"%PDF-"

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "letter.pdf"
        render_letter_pdf(_sample_letter(), path)
        assert path.exists()

    def test_with_profile_creates_pdf(self, tmp_path: Path):
        path = tmp_path / "letter_with_header.pdf"
        render_letter_pdf(_sample_letter(), path, profile=_sample_profile())
        assert path.exists()
        assert path.stat().st_size > 0
