"""Tests for the chat assistant LLM logic."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from emplaiyed.generation.chat_assistant import build_system_prompt, chat


class TestBuildSystemPrompt:
    def test_includes_cv_content(self):
        prompt = build_system_prompt("CV text here", "Letter", "Job desc", "Acme", "Dev")
        assert "CV text here" in prompt

    def test_includes_letter_content(self):
        prompt = build_system_prompt("CV", "My motivation letter", "Job desc", "Acme", "Dev")
        assert "My motivation letter" in prompt

    def test_includes_job_description(self):
        prompt = build_system_prompt("CV", "Letter", "Build REST APIs in Python", "Acme", "Dev")
        assert "Build REST APIs in Python" in prompt

    def test_includes_company(self):
        prompt = build_system_prompt("CV", "Letter", "Job desc", "BigCorp", "Dev")
        assert "BigCorp" in prompt

    def test_includes_title(self):
        prompt = build_system_prompt("CV", "Letter", "Job desc", "Acme", "Cloud Architect")
        assert "Cloud Architect" in prompt

    def test_instructs_paste_ready(self):
        prompt = build_system_prompt("CV", "Letter", "Job desc", "Acme", "Dev")
        assert "paste" in prompt.lower()

    def test_instructs_match_language(self):
        prompt = build_system_prompt("CV", "Letter", "Job desc", "Acme", "Dev")
        assert "language" in prompt.lower()


class TestChat:
    async def test_returns_string(self):
        model = TestModel(custom_output_text="Hello from the LLM")
        result = await chat(
            "Write a short intro",
            system_prompt="You are helpful.",
            _model_override=model,
        )
        assert isinstance(result, str)

    async def test_returns_model_output(self):
        model = TestModel(custom_output_text="Generated answer")
        result = await chat(
            "Answer this question",
            system_prompt="You are helpful.",
            _model_override=model,
        )
        assert result == "Generated answer"

    async def test_model_override_bypasses_api_key(self):
        """TestModel should work without any API key configured."""
        model = TestModel(custom_output_text="No key needed")
        result = await chat(
            "test",
            system_prompt="test",
            _model_override=model,
        )
        assert result == "No key needed"
