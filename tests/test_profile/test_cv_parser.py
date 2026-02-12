"""Tests for emplaiyed.profile.cv_parser — no real API calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import Profile
from emplaiyed.profile.cv_parser import extract_text, parse_cv, parse_cv_text

# Path to the real CV used for extraction tests
_CV_PDF_PATH = Path(__file__).resolve().parents[2] / ".." / "files" / "cv.pdf"


# ---------------------------------------------------------------------------
# extract_text tests
# ---------------------------------------------------------------------------

class TestExtractText:
    """Tests for the extract_text() function."""

    def test_reads_plain_text_file(self, tmp_path: Path) -> None:
        """Plain text files should be read directly."""
        cv = tmp_path / "resume.txt"
        cv.write_text("Jonathan Pelletier\nSoftware Engineer", encoding="utf-8")
        result = extract_text(cv)
        assert "Jonathan Pelletier" in result
        assert "Software Engineer" in result

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        """A missing file should raise FileNotFoundError."""
        missing = tmp_path / "does_not_exist.pdf"
        with pytest.raises(FileNotFoundError, match="File not found"):
            extract_text(missing)

    def test_raises_value_error_on_empty_file(self, tmp_path: Path) -> None:
        """An empty file should raise ValueError."""
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="No text could be extracted"):
            extract_text(empty)

    def test_reads_markdown_file(self, tmp_path: Path) -> None:
        """Non-PDF text formats should be read as plain text."""
        cv = tmp_path / "resume.md"
        cv.write_text("# Resume\n\nJohn Doe", encoding="utf-8")
        result = extract_text(cv)
        assert "John Doe" in result

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """Extracted text should have leading/trailing whitespace stripped."""
        cv = tmp_path / "resume.txt"
        cv.write_text("  \n  Hello World  \n  ", encoding="utf-8")
        result = extract_text(cv)
        assert result == "Hello World"

    def test_reads_pdf_file(self, tmp_path: Path) -> None:
        """PDF files should be parsed via pdfminer."""
        # Create a minimal valid PDF
        pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            b"/MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            b"4 0 obj\n<< /Length 44 >>\nstream\n"
            b"BT /F1 12 Tf 100 700 Td (Hello PDF) Tj ET\n"
            b"endstream\nendobj\n"
            b"5 0 obj\n<< /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >> endobj\n"
            b"xref\n0 6\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"0000000296 00000 n \n"
            b"0000000392 00000 n \n"
            b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
            b"startxref\n470\n%%EOF\n"
        )
        pdf = tmp_path / "resume.pdf"
        pdf.write_bytes(pdf_content)
        result = extract_text(pdf)
        assert "Hello" in result


# ---------------------------------------------------------------------------
# parse_cv_text tests
# ---------------------------------------------------------------------------

class TestParseCvText:
    """Tests for parse_cv_text() using TestModel."""

    async def test_returns_profile_instance(self) -> None:
        """parse_cv_text should return a Profile instance."""
        result = await parse_cv_text(
            "Jonathan Pelletier\njonathan@example.com\nPython, AWS",
            _model_override=TestModel(),
        )
        assert isinstance(result, Profile)

    async def test_profile_has_required_fields(self) -> None:
        """The returned Profile must have name and email (TestModel fills defaults)."""
        result = await parse_cv_text(
            "Some CV text",
            _model_override=TestModel(),
        )
        assert isinstance(result.name, str)
        assert isinstance(result.email, str)

    async def test_skills_is_list(self) -> None:
        """skills should always be a list."""
        result = await parse_cv_text(
            "Python, TypeScript, Docker",
            _model_override=TestModel(),
        )
        assert isinstance(result.skills, list)


# ---------------------------------------------------------------------------
# parse_cv tests
# ---------------------------------------------------------------------------

class TestParseCv:
    """Tests for the full parse_cv() pipeline."""

    async def test_parse_cv_from_text_file(self, tmp_path: Path) -> None:
        """parse_cv should work end-to-end with a text file."""
        cv = tmp_path / "resume.txt"
        cv.write_text(
            "Jane Doe\njane@example.com\nSenior Engineer at BigCorp\n"
            "Skills: Python, Go, Kubernetes",
            encoding="utf-8",
        )
        result = await parse_cv(cv, _model_override=TestModel())
        assert isinstance(result, Profile)

    async def test_parse_cv_file_not_found(self, tmp_path: Path) -> None:
        """parse_cv should raise FileNotFoundError for missing files."""
        missing = tmp_path / "nope.pdf"
        with pytest.raises(FileNotFoundError):
            await parse_cv(missing, _model_override=TestModel())

    async def test_parse_cv_empty_file(self, tmp_path: Path) -> None:
        """parse_cv should raise ValueError for empty files."""
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="No text could be extracted"):
            await parse_cv(empty, _model_override=TestModel())


# ---------------------------------------------------------------------------
# Real CV PDF extraction tests
# ---------------------------------------------------------------------------

_skip_no_cv = pytest.mark.skipif(
    not _CV_PDF_PATH.exists(),
    reason=f"Real CV not found at {_CV_PDF_PATH}",
)


@_skip_no_cv
class TestRealCvExtraction:
    """Tests using the actual cv.pdf to verify text extraction quality.

    These tests verify that pdfminer extracts the expected content from
    Jonathan's real CV. They do NOT call the LLM — they only test
    extract_text().
    """

    def test_extracts_name(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "Jonathan Pelletier" in text

    def test_extracts_email(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "jonathan.pelletier-aafz@thecloudco.ca" in text

    def test_extracts_phone(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "438" in text
        assert "876" in text

    def test_extracts_location(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "Longueuil" in text

    def test_extracts_certifications(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "AWS Certified Security" in text
        assert "AWS Certified Big Data" in text
        assert "AWS Certified Advanced Networking" in text
        assert "AWS Certified Solutions Architect" in text

    def test_extracts_certification_dates(self) -> None:
        """Certification date ranges MUST be present in the extracted text."""
        text = extract_text(_CV_PDF_PATH)
        # The CV shows "2019 - 2022" and "2018 - 2021" for cert dates
        assert "2019" in text
        assert "2022" in text
        assert "2018" in text
        assert "2021" in text

    def test_extracts_employers(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "Croesus" in text
        assert "Bell Canada" in text
        assert "Onica" in text or "Rackspace" in text
        assert "National Bank" in text
        assert "Mtrip" in text

    def test_extracts_skills(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "Python" in text
        assert "SQL" in text
        assert "TypeScript" in text
        assert "Docker" in text
        assert "Terraform" in text

    def test_extracts_education(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "Polytechnique" in text
        assert "Computer Engineering" in text

    def test_extracts_employment_dates(self) -> None:
        """Employment start/end dates must be present."""
        text = extract_text(_CV_PDF_PATH)
        assert "2021" in text  # Croesus start
        assert "2018" in text  # Onica start
        assert "2015" in text  # National Bank start
        assert "2013" in text  # Mtrip start

    def test_text_is_non_trivial_length(self) -> None:
        """The CV has substantial content — extracted text should be long."""
        text = extract_text(_CV_PDF_PATH)
        # Jonathan's CV is ~1 page with dense content
        assert len(text) > 500


@_skip_no_cv
class TestProfileSchemaConstraints:
    """Tests that verify the Profile schema enforces the design rules."""

    def test_profile_has_no_summary_field(self) -> None:
        """Summary is derived, not stored. The Profile model must not have it."""
        assert "summary" not in Profile.model_fields

    def test_certification_has_expiry_date(self) -> None:
        """Certifications must support date ranges (obtained + expiry)."""
        from emplaiyed.core.models import Certification
        assert "date_obtained" in Certification.model_fields
        assert "expiry_date" in Certification.model_fields

    def test_work_arrangement_is_list(self) -> None:
        """work_arrangement must be a list to capture multiple preferences."""
        from emplaiyed.core.models import Aspirations
        asp = Aspirations(work_arrangement=["remote", "hybrid", "on-site"])
        assert asp.work_arrangement == ["remote", "hybrid", "on-site"]

    def test_work_arrangement_rejects_string(self) -> None:
        """Passing a bare string to work_arrangement must fail validation."""
        from pydantic import ValidationError
        from emplaiyed.core.models import Aspirations
        with pytest.raises(ValidationError):
            Aspirations(work_arrangement="remote")  # type: ignore[arg-type]
