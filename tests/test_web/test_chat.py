"""Tests for the chat WebSocket endpoint."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from emplaiyed.api.app import create_app
from emplaiyed.api.deps import get_db, get_data_dir, get_profile
from emplaiyed.core.database import init_db, save_application, save_opportunity
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "test.db")
    conn.close()
    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@pytest.fixture
def sample_opp() -> Opportunity:
    return Opportunity(
        id="opp-chat-test",
        source="jobbank",
        source_url="https://example.com/job/42",
        company="ChatCorp",
        title="ML Engineer",
        description="Build ML pipelines.\n\nRequirements:\n- Python\n- PyTorch",
        location="Toronto, ON",
        scraped_at=datetime(2025, 7, 1, 10, 0, 0),
    )


@pytest.fixture
def sample_app() -> Application:
    return Application(
        id="app-chat-test-001",
        opportunity_id="opp-chat-test",
        status=ApplicationStatus.SCORED,
        score=75,
        justification="Good ML match",
        created_at=datetime(2025, 7, 1, 11, 0, 0),
        updated_at=datetime(2025, 7, 1, 11, 0, 0),
    )


def _make_db_override(conn: sqlite3.Connection):
    def override():
        yield conn

    return override


@pytest.fixture
def client(
    tmp_db: sqlite3.Connection,
    sample_opp: Opportunity,
    sample_app: Application,
    tmp_path: Path,
) -> TestClient:
    save_opportunity(tmp_db, sample_opp)
    save_application(tmp_db, sample_app)

    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


@pytest.fixture
def client_empty(tmp_db: sqlite3.Connection, tmp_path: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _make_db_override(tmp_db)
    app.dependency_overrides[get_profile] = lambda: None
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper to build a mock streaming agent
# ---------------------------------------------------------------------------


def _make_mock_agent(chunks: list[str]):
    """Return a mock Agent whose run_stream yields the given chunks."""

    class FakeStreamResult:
        async def stream_text(self, *, delta: bool = False):
            for chunk in chunks:
                yield chunk

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    mock_agent = MagicMock()
    mock_agent.run_stream = MagicMock(return_value=FakeStreamResult())
    return mock_agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatWebSocket:
    def test_connect_and_receive_stream(self, client: TestClient) -> None:
        """Send a query and receive streamed chunks + done message."""
        chunks = ["Hello", " world", "!"]
        mock_agent = _make_mock_agent(chunks)

        with (
            patch("emplaiyed.api.routes.chat.Agent", return_value=mock_agent),
            patch("emplaiyed.api.routes.chat.get_api_key", return_value="fake-key"),
            patch("emplaiyed.api.routes.chat.OpenAIChatModel"),
            patch("emplaiyed.api.routes.chat.OpenRouterProvider"),
        ):
            with client.websocket_connect("/ws/chat/app-chat-test-001") as ws:
                ws.send_text("Tell me about this role")

                received = []
                while True:
                    msg = ws.receive_json()
                    received.append(msg)
                    if msg["type"] in ("done", "error"):
                        break

                # Should have chunk messages followed by done
                chunk_msgs = [m for m in received if m["type"] == "chunk"]
                assert len(chunk_msgs) == 3
                assert chunk_msgs[0]["data"] == "Hello"
                assert chunk_msgs[1]["data"] == " world"
                assert chunk_msgs[2]["data"] == "!"
                assert received[-1]["type"] == "done"

    def test_app_not_found(self, client_empty: TestClient) -> None:
        """Connecting with a nonexistent app ID should return an error."""
        with client_empty.websocket_connect("/ws/chat/nonexistent-id") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["data"].lower()

    def test_opportunity_not_found(
        self, tmp_db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """App exists but opportunity is missing — should error."""
        # Create a temporary opportunity, save the app, then delete the opp
        tmp_opp = Opportunity(
            id="opp-temp",
            source="manual",
            company="TempCo",
            title="Temp",
            description="Temporary opportunity",
            scraped_at=datetime(2025, 7, 1),
        )
        save_opportunity(tmp_db, tmp_opp)
        orphan_app = Application(
            id="app-orphan",
            opportunity_id="opp-temp",
            status=ApplicationStatus.SCORED,
            score=50,
            created_at=datetime(2025, 7, 1),
            updated_at=datetime(2025, 7, 1),
        )
        save_application(tmp_db, orphan_app)
        # Disable FK checks temporarily to delete the opportunity
        tmp_db.execute("PRAGMA foreign_keys=OFF;")
        tmp_db.execute("DELETE FROM opportunities WHERE id = 'opp-temp'")
        tmp_db.commit()
        tmp_db.execute("PRAGMA foreign_keys=ON;")

        app = create_app()
        app.dependency_overrides[get_db] = _make_db_override(tmp_db)
        app.dependency_overrides[get_profile] = lambda: None
        app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
        client = TestClient(app)

        with client.websocket_connect("/ws/chat/app-orphan") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["data"].lower()

    def test_llm_error_returns_error_message(self, client: TestClient) -> None:
        """If the LLM raises, the error should be sent back over WebSocket."""
        mock_agent = MagicMock()
        mock_agent.run_stream = MagicMock(
            side_effect=RuntimeError("API quota exceeded")
        )

        with (
            patch("emplaiyed.api.routes.chat.Agent", return_value=mock_agent),
            patch("emplaiyed.api.routes.chat.get_api_key", return_value="fake-key"),
            patch("emplaiyed.api.routes.chat.OpenAIChatModel"),
            patch("emplaiyed.api.routes.chat.OpenRouterProvider"),
        ):
            with client.websocket_connect("/ws/chat/app-chat-test-001") as ws:
                ws.send_text("What should I prepare?")
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert "API quota exceeded" in msg["data"]

    def test_multiple_queries(self, client: TestClient) -> None:
        """Can send multiple queries in succession."""

        call_count = 0

        def make_agent_for_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_agent(["First ", "response"])
            return _make_mock_agent(["Second ", "response"])

        with (
            patch("emplaiyed.api.routes.chat.Agent", side_effect=make_agent_for_call),
            patch("emplaiyed.api.routes.chat.get_api_key", return_value="fake-key"),
            patch("emplaiyed.api.routes.chat.OpenAIChatModel"),
            patch("emplaiyed.api.routes.chat.OpenRouterProvider"),
        ):
            with client.websocket_connect("/ws/chat/app-chat-test-001") as ws:
                # First query
                ws.send_text("First question")
                msgs1 = []
                while True:
                    msg = ws.receive_json()
                    msgs1.append(msg)
                    if msg["type"] == "done":
                        break
                assert any(m["data"] == "First " for m in msgs1 if m["type"] == "chunk")

                # Second query
                ws.send_text("Second question")
                msgs2 = []
                while True:
                    msg = ws.receive_json()
                    msgs2.append(msg)
                    if msg["type"] == "done":
                        break
                assert any(
                    m["data"] == "Second " for m in msgs2 if m["type"] == "chunk"
                )

    def test_reads_asset_files(self, client: TestClient, tmp_path: Path) -> None:
        """When asset files exist, they should be read into the system prompt."""
        # Create mock asset files
        asset_dir = tmp_path / "data" / "assets" / "app-chat-test-001"
        asset_dir.mkdir(parents=True)
        (asset_dir / "cv.md").write_text("# My CV\nExperienced ML engineer")
        (asset_dir / "letter.md").write_text("Dear Hiring Manager,\n...")

        captured_prompt = {}

        def capture_agent(*args, **kwargs):
            captured_prompt["system_prompt"] = kwargs.get(
                "system_prompt", args[2] if len(args) > 2 else None
            )
            return _make_mock_agent(["OK"])

        with (
            patch("emplaiyed.api.routes.chat.Agent", side_effect=capture_agent),
            patch("emplaiyed.api.routes.chat.get_asset_dir", return_value=asset_dir),
            patch("emplaiyed.api.routes.chat.get_api_key", return_value="fake-key"),
            patch("emplaiyed.api.routes.chat.OpenAIChatModel"),
            patch("emplaiyed.api.routes.chat.OpenRouterProvider"),
        ):
            with client.websocket_connect("/ws/chat/app-chat-test-001") as ws:
                ws.send_text("Test")
                while True:
                    msg = ws.receive_json()
                    if msg["type"] in ("done", "error"):
                        break

        # The Agent constructor receives system_prompt as a kwarg
        assert captured_prompt.get("system_prompt") is not None

    def test_no_assets_uses_placeholder(self, client: TestClient) -> None:
        """When no asset files exist, placeholder text should be used."""
        captured_prompts = []

        original_build = None

        def capture_build(*args, **kwargs):
            captured_prompts.append(args)
            # Call the real function
            from emplaiyed.generation.chat_assistant import build_system_prompt

            return build_system_prompt(*args, **kwargs)

        mock_agent = _make_mock_agent(["OK"])

        with (
            patch(
                "emplaiyed.api.routes.chat.build_system_prompt",
                side_effect=capture_build,
            ),
            patch("emplaiyed.api.routes.chat.Agent", return_value=mock_agent),
            patch("emplaiyed.api.routes.chat.get_api_key", return_value="fake-key"),
            patch("emplaiyed.api.routes.chat.OpenAIChatModel"),
            patch("emplaiyed.api.routes.chat.OpenRouterProvider"),
        ):
            with client.websocket_connect("/ws/chat/app-chat-test-001") as ws:
                ws.send_text("Test")
                while True:
                    msg = ws.receive_json()
                    if msg["type"] in ("done", "error"):
                        break

        # build_system_prompt was called with placeholder text for cv and letter
        assert len(captured_prompts) == 1
        cv_arg = captured_prompts[0][0]
        letter_arg = captured_prompts[0][1]
        assert "No CV generated" in cv_arg
        assert "No cover letter generated" in letter_arg
