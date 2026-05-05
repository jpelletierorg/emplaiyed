"""Tests for confirmation evidence detection."""

from __future__ import annotations

from emplaiyed.apply.artifacts import _find_confirmation


class TestFindConfirmation:
    def test_english_thank_you(self):
        text = "Thank you for applying! We have received your application."
        result = _find_confirmation(text)
        assert result is not None
        assert "thank you" in result.lower()

    def test_french_merci(self):
        text = "Merci pour votre candidature. Nous reviendrons vers vous."
        result = _find_confirmation(text)
        assert result is not None

    def test_application_received(self):
        text = "Your application has been received. We will review it shortly."
        result = _find_confirmation(text)
        assert result is not None

    def test_successfully_submitted(self):
        text = "You have successfully submitted your application to Acme Corp."
        result = _find_confirmation(text)
        assert result is not None

    def test_no_match(self):
        text = "Please fill out the form below to apply for this position."
        result = _find_confirmation(text)
        assert result is None

    def test_french_candidature_envoyee(self):
        text = "Votre candidature a bien ete envoyee."
        result = _find_confirmation(text)
        assert result is not None

    def test_empty_text(self):
        assert _find_confirmation("") is None
