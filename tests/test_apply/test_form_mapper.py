"""Tests for the form field mapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from emplaiyed.apply.form_mapper import FormPlan, build_form_plan
from emplaiyed.core.models import Address, Profile


@pytest.fixture
def profile():
    return Profile(
        name="Jean Dupont",
        email="jean@example.com",
        phone="+1-514-555-1234",
        linkedin="https://linkedin.com/in/jean",
        github="https://github.com/jean",
        address=Address(city="Montreal", province_state="QC", country="Canada"),
    )


class TestBuildFormPlan:
    def test_maps_required_name_fields(self, profile):
        fields = [
            {
                "selector": "#first",
                "name": "first_name",
                "label": "First Name",
                "required": True,
                "type": "text",
            },
            {
                "selector": "#last",
                "name": "last_name",
                "label": "Last Name",
                "required": True,
                "type": "text",
            },
        ]
        plan = build_form_plan(profile, fields)
        assert len(plan.text_fields) == 2
        assert plan.text_fields[0].value == "Jean"
        assert plan.text_fields[1].value == "Dupont"
        assert not plan.unmapped_required

    def test_maps_email_and_phone(self, profile):
        fields = [
            {
                "selector": "#email",
                "name": "email",
                "label": "Email",
                "required": True,
                "type": "email",
            },
            {
                "selector": "#phone",
                "name": "phone",
                "label": "Phone",
                "required": True,
                "type": "tel",
            },
        ]
        plan = build_form_plan(profile, fields)
        assert len(plan.text_fields) == 2
        assert plan.text_fields[0].value == "jean@example.com"
        assert plan.text_fields[1].value == "+1-514-555-1234"

    def test_skips_optional_fields(self, profile):
        fields = [
            {
                "selector": "#email",
                "name": "email",
                "label": "Email",
                "required": True,
                "type": "email",
            },
            {
                "selector": "#cover",
                "name": "cover_letter_text",
                "label": "Cover letter (optional)",
                "required": False,
                "type": "textarea",
            },
        ]
        plan = build_form_plan(profile, fields)
        assert len(plan.text_fields) == 1  # only email

    def test_file_upload_resume(self, profile, tmp_path):
        resume = tmp_path / "cv.pdf"
        resume.write_bytes(b"pdf content")

        fields = [
            {
                "selector": "#resume",
                "name": "resume",
                "label": "Resume",
                "required": True,
                "type": "file",
            },
        ]
        plan = build_form_plan(profile, fields, resume_path=resume)
        assert len(plan.file_uploads) == 1
        assert plan.file_uploads[0].value == str(resume)

    def test_file_upload_letter(self, profile, tmp_path):
        letter = tmp_path / "letter.pdf"
        letter.write_bytes(b"pdf content")

        fields = [
            {
                "selector": "#letter",
                "name": "cover_letter",
                "label": "Cover Letter",
                "required": True,
                "type": "file",
            },
        ]
        plan = build_form_plan(profile, fields, letter_path=letter)
        assert len(plan.file_uploads) == 1

    def test_unmapped_required_field(self, profile):
        fields = [
            {
                "selector": "#salary",
                "name": "salary_expectation",
                "label": "Expected Salary",
                "required": True,
                "type": "text",
            },
        ]
        plan = build_form_plan(profile, fields)
        assert len(plan.unmapped_required) == 1

    def test_missing_resume_required(self, profile):
        fields = [
            {
                "selector": "#resume",
                "name": "resume",
                "label": "Resume",
                "required": True,
                "type": "file",
            },
        ]
        plan = build_form_plan(profile, fields, resume_path=None)
        assert len(plan.unmapped_required) == 1

    def test_linkedin_mapping(self, profile):
        fields = [
            {
                "selector": "#li",
                "name": "linkedin",
                "label": "LinkedIn URL",
                "required": True,
                "type": "text",
            },
        ]
        plan = build_form_plan(profile, fields)
        assert len(plan.text_fields) == 1
        assert plan.text_fields[0].value == "https://linkedin.com/in/jean"

    def test_full_name_mapping(self, profile):
        fields = [
            {
                "selector": "#name",
                "name": "full_name",
                "label": "Your Name",
                "required": True,
                "type": "text",
            },
        ]
        plan = build_form_plan(profile, fields)
        assert len(plan.text_fields) == 1
        assert plan.text_fields[0].value == "Jean Dupont"
