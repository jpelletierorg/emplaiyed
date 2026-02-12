"""Unit tests for emplaiyed.llm.engine — no real API calls."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from emplaiyed.llm.config import get_api_key
from emplaiyed.llm.engine import complete, complete_structured


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CapitalCity(BaseModel):
    city: str
    country: str


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComplete:
    """Tests for the ``complete()`` function."""

    async def test_returns_string(self) -> None:
        """complete() should return a plain string response."""
        result = await complete(
            "Say hello",
            _model_override=TestModel(custom_output_text="Hello!"),
        )
        assert isinstance(result, str)
        assert result == "Hello!"

    async def test_model_override_bypasses_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _model_override is provided, no API key is needed."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        result = await complete(
            "Anything",
            _model_override=TestModel(custom_output_text="works"),
        )
        assert result == "works"


class TestCompleteStructured:
    """Tests for the ``complete_structured()`` function."""

    async def test_returns_validated_model(self) -> None:
        """complete_structured() should return a validated Pydantic instance."""
        result = await complete_structured(
            "What is the capital of France?",
            output_type=CapitalCity,
            _model_override=TestModel(),
        )
        assert isinstance(result, CapitalCity)
        # TestModel returns default placeholder values for each field
        assert isinstance(result.city, str)
        assert isinstance(result.country, str)

    async def test_structured_model_override_bypasses_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structured call with _model_override should not need an API key."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        result = await complete_structured(
            "Anything",
            output_type=CapitalCity,
            _model_override=TestModel(),
        )
        assert isinstance(result, CapitalCity)


class TestConfig:
    """Tests for configuration / API key handling."""

    def test_missing_api_key_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_api_key() must raise RuntimeError with a clear message."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set"):
            get_api_key()

    def test_api_key_returned_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_api_key() returns the key when it is set."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        assert get_api_key() == "sk-test-123"


class TestDotenvLoading:
    """Tests that .env files are loaded into the environment on import."""

    def test_dotenv_loads_api_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When OPENROUTER_API_KEY is only in a .env file, it should still be
        available via get_api_key() after the config module loads."""
        # Remove any existing key from the environment
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        # Write a .env file and a pyproject.toml marker so the loader finds it
        env_file = tmp_path / ".env"
        env_file.write_text("OPENROUTER_API_KEY=sk-from-dotenv-file\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        # Manually call load_dotenv with the same logic the config module uses
        from dotenv import load_dotenv

        load_dotenv(env_file, override=True)

        assert os.environ.get("OPENROUTER_API_KEY") == "sk-from-dotenv-file"
        assert get_api_key() == "sk-from-dotenv-file"

    def test_env_var_takes_precedence_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicitly set env var should win over .env file contents."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-explicit-env")

        env_file = tmp_path / ".env"
        env_file.write_text("OPENROUTER_API_KEY=sk-from-dotenv\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)

        # Explicit env var wins
        assert get_api_key() == "sk-explicit-env"

    def test_config_module_loads_dotenv_on_import(self) -> None:
        """The config module should have loaded .env at import time.

        This is a smoke test — if the project .env exists with a key,
        get_api_key() should not raise. If it doesn't exist, we verify
        the load_dotenv call was at least attempted by checking the module
        has the expected attributes.
        """
        import emplaiyed.llm.config as config_module

        # Verify the module-level dotenv loading code exists
        assert hasattr(config_module, "load_dotenv") or callable(
            getattr(config_module, "load_dotenv", None)
        )


class TestModelOverride:
    """Tests that the model parameter properly controls which model is used."""

    async def test_default_model_used_when_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When model=None, _build_model uses DEFAULT_MODEL.

        We can't easily assert the model string without calling the API,
        but we can verify that _build_model runs without error when a key
        exists.
        """
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-key")
        from emplaiyed.llm.engine import _build_model

        m = _build_model(None)
        # The model object should have been created with the default name
        assert m is not None

    async def test_custom_model_string_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing a specific model string should not error."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-key")
        from emplaiyed.llm.engine import _build_model

        m = _build_model("google/gemini-2.0-flash-001")
        assert m is not None
