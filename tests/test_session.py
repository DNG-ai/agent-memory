"""Tests for session management."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_memory.config import Config
from agent_memory.session import Session, SessionManager
from agent_memory.store import MemoryStore


@pytest.fixture
def session_manager(config: Config, store: MemoryStore, temp_dir: Path) -> SessionManager:
    """Create a test session manager."""
    project_path = temp_dir / "test-project"
    project_path.mkdir(exist_ok=True)
    return SessionManager(config, store, None, project_path)


class TestSession:
    """Tests for Session dataclass."""

    def test_session_to_dict(self) -> None:
        """Test Session.to_dict() method."""
        from datetime import datetime, timezone

        session = Session(
            id="sess_test123",
            project_path="/test/path",
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ended_at=None,
            summary_count=2,
            metadata={"key": "value"},
        )

        data = session.to_dict()

        assert data["id"] == "sess_test123"
        assert data["project_path"] == "/test/path"
        assert "2024-01-01" in data["started_at"]
        assert data["ended_at"] is None
        assert data["summary_count"] == 2
        assert data["metadata"] == {"key": "value"}

    def test_session_from_dict(self) -> None:
        """Test Session.from_dict() method."""
        data = {
            "id": "sess_test123",
            "project_path": "/test/path",
            "started_at": "2024-01-01T00:00:00+00:00",
            "ended_at": None,
            "summary_count": 2,
            "metadata": {"key": "value"},
        }

        session = Session.from_dict(data)

        assert session.id == "sess_test123"
        assert session.project_path == "/test/path"
        assert session.ended_at is None
        assert session.summary_count == 2


class TestSessionManager:
    """Tests for SessionManager."""

    def test_start_session(self, session_manager: SessionManager) -> None:
        """Test starting a new session."""
        session = session_manager.start_session()

        assert session.id.startswith("sess_")
        assert session.ended_at is None
        assert session_manager.get_current_session() == session

    def test_end_session(self, session_manager: SessionManager) -> None:
        """Test ending a session."""
        session = session_manager.start_session()

        ended = session_manager.end_session()

        assert ended is not None
        assert ended.id == session.id
        assert ended.ended_at is not None
        assert session_manager.get_current_session() is None

    def test_get_session(self, session_manager: SessionManager) -> None:
        """Test getting a session by ID."""
        session = session_manager.start_session()

        retrieved = session_manager.get_session(session.id)

        assert retrieved is not None
        assert retrieved.id == session.id

    def test_get_last_session(self, session_manager: SessionManager) -> None:
        """Test getting the last session."""
        session1 = session_manager.start_session()
        session_manager.end_session()

        session2 = session_manager.start_session()

        last = session_manager.get_last_session()

        assert last is not None
        assert last.id == session2.id

    def test_list_sessions(self, session_manager: SessionManager) -> None:
        """Test listing sessions."""
        session_manager.start_session()
        session_manager.end_session()
        session_manager.start_session()
        session_manager.end_session()
        session_manager.start_session()

        sessions = session_manager.list_sessions()

        assert len(sessions) == 3

    def test_list_sessions_limit(self, session_manager: SessionManager) -> None:
        """Test listing sessions with limit."""
        for _ in range(5):
            session_manager.start_session()
            session_manager.end_session()

        sessions = session_manager.list_sessions(limit=3)

        assert len(sessions) == 3

    def test_add_summary(self, session_manager: SessionManager) -> None:
        """Test adding a session summary."""
        session = session_manager.start_session()

        memory = session_manager.add_summary("Test summary content")

        assert memory.category == "session_summary"
        assert memory.content == "Test summary content"
        assert memory.metadata.get("session_id") == session.id

    def test_get_session_summaries(self, session_manager: SessionManager) -> None:
        """Test getting summaries for a session."""
        session = session_manager.start_session()
        session_manager.add_summary("Summary 1")
        session_manager.add_summary("Summary 2")

        summaries = session_manager.get_session_summaries(session.id)

        assert len(summaries) == 2

    def test_load_last_session_context(self, session_manager: SessionManager) -> None:
        """Test loading last session context."""
        session = session_manager.start_session()
        session_manager.add_summary("Important context")
        session_manager.end_session()

        context = session_manager.load_last_session_context()

        assert len(context) == 1
        assert context[0].content == "Important context"

    def test_should_summarize(self, session_manager: SessionManager) -> None:
        """Test should_summarize logic."""
        # Default interval is 20
        assert session_manager.should_summarize(0) is False
        assert session_manager.should_summarize(10) is False
        assert session_manager.should_summarize(20) is True
        assert session_manager.should_summarize(40) is True

    def test_session_with_metadata(self, session_manager: SessionManager) -> None:
        """Test starting session with metadata."""
        session = session_manager.start_session(metadata={"agent": "opencode", "version": "1.0"})

        assert session.metadata["agent"] == "opencode"
        assert session.metadata["version"] == "1.0"
