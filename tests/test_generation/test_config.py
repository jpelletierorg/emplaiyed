"""Tests for generation config constants."""

from emplaiyed.generation.config import (
    CV_MODEL,
    CV_SYSTEM_PROMPT,
    EAGER_TOP_N,
    LETTER_MODEL,
    LETTER_SYSTEM_PROMPT,
)


class TestGenerationConfig:
    def test_cv_model_is_valid_openrouter_id(self):
        assert "/" in CV_MODEL
        assert "claude" in CV_MODEL.lower() or "gpt" in CV_MODEL.lower() or "anthropic" in CV_MODEL

    def test_letter_model_is_valid_openrouter_id(self):
        assert "/" in LETTER_MODEL

    def test_eager_top_n_is_positive(self):
        assert EAGER_TOP_N > 0

    def test_cv_system_prompt_not_empty(self):
        assert len(CV_SYSTEM_PROMPT.strip()) > 50

    def test_letter_system_prompt_not_empty(self):
        assert len(LETTER_SYSTEM_PROMPT.strip()) > 50

    def test_cv_prompt_mentions_no_fabrication(self):
        assert "fabricat" in CV_SYSTEM_PROMPT.lower()

    def test_letter_prompt_mentions_first_person(self):
        assert "first person" in LETTER_SYSTEM_PROMPT.lower()
