"""Tests for PDF rendering of CV and letter."""

from __future__ import annotations

from pathlib import Path

from emplaiyed.generation.cv_generator import CVExperience, GeneratedCV
from emplaiyed.generation.letter_generator import GeneratedLetter
from emplaiyed.rendering.pdf_renderer import render_cv_pdf, render_letter_pdf


def _sample_cv() -> GeneratedCV:
    return GeneratedCV(
        name="Alice Test",
        email="alice@example.com",
        phone="+1-555-0000",
        location="Montreal, QC",
        professional_title="Senior Cloud Architect",
        skills=["Python", "AWS", "Docker"],
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
        education=["M.Sc. Computer Science, Université Laval"],
        certifications=["AWS Solutions Architect (2023)"],
        languages=["French (Native)", "English (Fluent)"],
    )


def _sample_letter() -> GeneratedLetter:
    return GeneratedLetter(
        greeting="Dear Hiring Manager,",
        body="I am writing to express my interest in the Cloud Architect position.",
        closing="Sincerely,",
        signature_name="Alice Test",
    )


class TestRenderCVPDF:
    def test_creates_pdf_file(self, tmp_path: Path):
        path = tmp_path / "cv.pdf"
        render_cv_pdf(_sample_cv(), path)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_pdf_starts_with_pdf_header(self, tmp_path: Path):
        path = tmp_path / "cv.pdf"
        render_cv_pdf(_sample_cv(), path)
        header = path.read_bytes()[:5]
        assert header == b"%PDF-"

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "cv.pdf"
        render_cv_pdf(_sample_cv(), path)
        assert path.exists()

    def test_minimal_cv(self, tmp_path: Path):
        cv = GeneratedCV(
            name="Bob",
            email="bob@x.com",
            professional_title="Dev",
            skills=["Python"],
            experience=[],
            education=[],
        )
        path = tmp_path / "minimal.pdf"
        render_cv_pdf(cv, path)
        assert path.exists()
        assert path.stat().st_size > 0


class TestRenderLetterPDF:
    def test_creates_pdf_file(self, tmp_path: Path):
        path = tmp_path / "letter.pdf"
        render_letter_pdf(_sample_letter(), path)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_pdf_starts_with_pdf_header(self, tmp_path: Path):
        path = tmp_path / "letter.pdf"
        render_letter_pdf(_sample_letter(), path)
        header = path.read_bytes()[:5]
        assert header == b"%PDF-"

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "letter.pdf"
        render_letter_pdf(_sample_letter(), path)
        assert path.exists()
