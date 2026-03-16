"""Tests for contact extraction — LLM, regex, JSON-LD, and orchestrator."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic_ai.models.test import TestModel

from emplaiyed.contacts.extractor import (
    ExtractedContact,
    extract_and_save_contacts,
    extract_contact_jsonld,
    extract_contact_llm,
    extract_emails_regex,
)
from emplaiyed.core.database import (
    get_contacts_for_opportunity,
    init_db,
    save_contact,
    save_opportunity,
)
from emplaiyed.core.models import Contact, Opportunity


def _test_opportunity(**overrides) -> Opportunity:
    defaults = dict(
        source="talent",
        company="Test Corp",
        title="Software Engineer",
        description="We're hiring! Contact Jane at jane@testcorp.com for more info.",
        scraped_at=datetime.now(),
    )
    defaults.update(overrides)
    return Opportunity(**defaults)


# ---------------------------------------------------------------------------
# Regex extraction
# ---------------------------------------------------------------------------


class TestExtractEmailsRegex:
    def test_finds_standard_emails(self):
        text = "Send resume to recruiter@acme.com or apply at jobs.acme.com"
        emails = extract_emails_regex(text)
        assert "recruiter@acme.com" in emails

    def test_filters_generic_patterns(self):
        text = "noreply@acme.com no-reply@acme.com info@acme.com support@acme.com"
        emails = extract_emails_regex(text)
        assert len(emails) == 0

    def test_finds_multiple_emails(self):
        text = "Contact alice@co.com or bob@co.com"
        emails = extract_emails_regex(text)
        assert len(emails) == 2
        assert "alice@co.com" in emails
        assert "bob@co.com" in emails

    def test_empty_text(self):
        assert extract_emails_regex("") == []

    def test_no_emails(self):
        assert extract_emails_regex("This posting has no contact info") == []


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------


class TestExtractContactJsonld:
    def test_with_contact_point(self):
        hiring_org = {
            "name": "Acme Corp",
            "contactPoint": {
                "name": "Jane Smith",
                "email": "jane@acme.com",
                "telephone": "514-555-1234",
                "contactType": "Recruiter",
            },
        }
        result = extract_contact_jsonld(hiring_org)
        assert result is not None
        assert result.found is True
        assert result.name == "Jane Smith"
        assert result.email == "jane@acme.com"
        assert result.phone == "514-555-1234"
        assert result.title == "Recruiter"
        assert result.confidence == 0.9

    def test_with_application_contact(self):
        hiring_org = {
            "name": "Test Inc",
            "applicationContact": {
                "name": "Bob Recruiter",
                "email": "bob@test.com",
            },
        }
        result = extract_contact_jsonld(hiring_org)
        assert result is not None
        assert result.found is True
        assert result.name == "Bob Recruiter"

    def test_contact_point_as_list(self):
        hiring_org = {
            "name": "List Corp",
            "contactPoint": [
                {"name": "First", "email": "first@list.com"},
                {"name": "Second", "email": "second@list.com"},
            ],
        }
        result = extract_contact_jsonld(hiring_org)
        assert result is not None
        assert result.name == "First"

    def test_no_contact_point(self):
        hiring_org = {"name": "No Contact Corp"}
        result = extract_contact_jsonld(hiring_org)
        assert result is None

    def test_empty_contact_point(self):
        hiring_org = {"name": "Empty", "contactPoint": {}}
        result = extract_contact_jsonld(hiring_org)
        assert result is None

    def test_contact_point_no_useful_fields(self):
        hiring_org = {
            "name": "Useless",
            "contactPoint": {"contactType": "HR"},
        }
        result = extract_contact_jsonld(hiring_org)
        # No name, email, or phone — should return None
        assert result is None


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------


class TestExtractContactLlm:
    async def test_returns_extracted_contact(self):
        result = await extract_contact_llm(
            "Contact Jane Smith at jane@acme.com",
            _model_override=TestModel(),
        )
        assert isinstance(result, ExtractedContact)


# ---------------------------------------------------------------------------
# Orchestrator: extract_and_save_contacts
# ---------------------------------------------------------------------------


class TestExtractAndSaveContacts:
    def _make_db(self, tmp_path: Path):
        return init_db(tmp_path / "test.db")

    async def test_jsonld_path(self, tmp_path: Path):
        """When hiring_org has contactPoint, uses JSON-LD extraction."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(
            raw_data={
                "job_id": "123",
                "hiring_org": {
                    "name": "Acme",
                    "contactPoint": {
                        "name": "Jane",
                        "email": "jane@acme.com",
                    },
                },
            }
        )
        save_opportunity(conn, opp)

        contacts = await extract_and_save_contacts(conn, opp)
        assert len(contacts) == 1
        assert contacts[0].source == "json_ld"
        assert contacts[0].name == "Jane"
        assert contacts[0].email == "jane@acme.com"

    async def test_llm_fallback(self, tmp_path: Path):
        """When no JSON-LD, falls back to LLM extraction."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(raw_data={"job_id": "456"})
        save_opportunity(conn, opp)

        contacts = await extract_and_save_contacts(
            conn, opp, _model_override=TestModel()
        )
        # TestModel returns default values — found=False, so should fall back
        # to regex which should find jane@testcorp.com in the default description
        assert len(contacts) >= 1

    async def test_regex_fallback(self, tmp_path: Path):
        """When LLM returns found=False, falls back to regex."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(
            description="Apply to apply@company.com for this role.",
            raw_data={"job_id": "789"},
        )
        save_opportunity(conn, opp)

        contacts = await extract_and_save_contacts(
            conn, opp, _model_override=TestModel()
        )
        assert len(contacts) >= 1
        # Could be LLM or regex — either is fine

    async def test_skips_existing(self, tmp_path: Path):
        """If contacts already exist, returns them without re-extracting."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(raw_data={"job_id": "111"})
        save_opportunity(conn, opp)

        # Pre-save a contact
        existing = Contact(
            opportunity_id=opp.id,
            name="Pre-existing",
            email="pre@existing.com",
            source="manual",
            confidence=1.0,
        )
        save_contact(conn, existing)

        contacts = await extract_and_save_contacts(conn, opp)
        assert len(contacts) == 1
        assert contacts[0].name == "Pre-existing"

    async def test_force_reextracts(self, tmp_path: Path):
        """With force=True, re-extracts even if contacts exist."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(
            raw_data={
                "job_id": "222",
                "hiring_org": {
                    "name": "ForceCo",
                    "contactPoint": {
                        "name": "New Contact",
                        "email": "new@force.com",
                    },
                },
            }
        )
        save_opportunity(conn, opp)

        # Pre-save a contact
        existing = Contact(
            opportunity_id=opp.id,
            name="Old",
            source="manual",
            confidence=1.0,
        )
        save_contact(conn, existing)

        contacts = await extract_and_save_contacts(conn, opp, force=True)
        # Should find the JSON-LD contact
        assert any(c.name == "New Contact" for c in contacts)

    async def test_no_description_returns_empty(self, tmp_path: Path):
        """Opportunity with empty description and no raw_data contact info."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(description="", raw_data={"job_id": "333"})
        save_opportunity(conn, opp)

        contacts = await extract_and_save_contacts(
            conn, opp, _model_override=TestModel()
        )
        assert contacts == []

    async def test_contacts_persisted(self, tmp_path: Path):
        """Extracted contacts are saved to the database."""
        conn = self._make_db(tmp_path)
        opp = _test_opportunity(
            raw_data={
                "job_id": "444",
                "hiring_org": {
                    "name": "PersistCo",
                    "contactPoint": {
                        "name": "Saved",
                        "email": "saved@persist.com",
                    },
                },
            }
        )
        save_opportunity(conn, opp)

        await extract_and_save_contacts(conn, opp)

        # Verify they're in the DB
        db_contacts = get_contacts_for_opportunity(conn, opp.id)
        assert len(db_contacts) == 1
        assert db_contacts[0].name == "Saved"
