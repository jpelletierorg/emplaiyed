"""Tests for emplaiyed.profile.cv_parser -- no real API calls."""

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

    @pytest.mark.parametrize(
        "filename, content, expected",
        [
            ("resume.txt", "Jonathan Pelletier\nSoftware Engineer", "Jonathan Pelletier"),
            ("resume.md", "# Resume\n\nJohn Doe", "John Doe"),
        ],
    )
    def test_reads_text_formats(
        self, tmp_path: Path, filename: str, content: str, expected: str
    ) -> None:
        """Plain text and markdown files should be read directly."""
        cv = tmp_path / filename
        cv.write_text(content, encoding="utf-8")
        result = extract_text(cv)
        assert expected in result

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
# parse_cv tests (full pipeline)
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
    Jonathan's real CV. They do NOT call the LLM -- they only test
    extract_text().
    """

    @pytest.mark.parametrize(
        "expected_text",
        [
            "Jonathan Pelletier",
            "jonathan.pelletier-aafz@thecloudco.ca",
            "Longueuil",
            "Python",
            "SQL",
            "TypeScript",
            "Docker",
            "Terraform",
            "Polytechnique",
            "Computer Engineering",
        ],
        ids=[
            "name",
            "email",
            "location",
            "skill-python",
            "skill-sql",
            "skill-typescript",
            "skill-docker",
            "skill-terraform",
            "education-institution",
            "education-field",
        ],
    )
    def test_extracts_expected_content(self, expected_text: str) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert expected_text in text

    def test_extracts_phone(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "438" in text
        assert "876" in text

    def test_extracts_certifications(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "AWS Certified Security" in text
        assert "AWS Certified Big Data" in text
        assert "AWS Certified Advanced Networking" in text
        assert "AWS Certified Solutions Architect" in text

    def test_extracts_certification_dates(self) -> None:
        """Certification date ranges MUST be present in the extracted text."""
        text = extract_text(_CV_PDF_PATH)
        for year in ["2019", "2022", "2018", "2021"]:
            assert year in text

    def test_extracts_employers(self) -> None:
        text = extract_text(_CV_PDF_PATH)
        assert "Croesus" in text
        assert "Bell Canada" in text
        assert "Onica" in text or "Rackspace" in text
        assert "National Bank" in text
        assert "Mtrip" in text

    def test_extracts_employment_dates(self) -> None:
        """Employment start/end dates must be present."""
        text = extract_text(_CV_PDF_PATH)
        for year in ["2021", "2018", "2015", "2013"]:
            assert year in text
