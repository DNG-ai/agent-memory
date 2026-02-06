"""Session management for agent-memory."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_memory.config import Config, get_project_path
from agent_memory.store import Memory, MemoryStore
from agent_memory.utils import generate_session_id, get_timestamp
from agent_memory.vector_store import VectorStore


@dataclass
class Session:
    """Represents an agent session."""

    id: str
    project_path: str
    started_at: datetime
    ended_at: datetime | None = None
    summary_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "project_path": self.project_path,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "summary_count": self.summary_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """Create from dictionary."""
        from agent_memory.utils import parse_timestamp

        return cls(
            id=data["id"],
            project_path=data["project_path"],
            started_at=parse_timestamp(data["started_at"]),
            ended_at=parse_timestamp(data["ended_at"]) if data.get("ended_at") else None,
            summary_count=data.get("summary_count", 0),
            metadata=data.get("metadata", {}),
        )


class SessionManager:
    """Manages agent sessions and summaries."""

    SESSIONS_FILE = "sessions.json"

    def __init__(
        self,
        config: Config,
        store: MemoryStore,
        vector_store: VectorStore | None = None,
        project_path: Path | None = None,
    ):
        """Initialize session manager.

        Args:
            config: Configuration object
            store: Memory store
            vector_store: Optional vector store
            project_path: Project path for session tracking
        """
        self.config = config
        self.store = store
        self.vector_store = vector_store
        self.project_path = project_path
        self._current_session: Session | None = None

    @property
    def sessions_file(self) -> Path:
        """Path to sessions file."""
        if self.project_path is None:
            return self.config.global_path / "summaries" / self.SESSIONS_FILE
        project_storage = get_project_path(self.config, self.project_path)
        return project_storage / "summaries" / self.SESSIONS_FILE

    def _load_sessions(self) -> list[Session]:
        """Load sessions from file."""
        if not self.sessions_file.exists():
            return []

        try:
            with open(self.sessions_file) as f:
                data = json.load(f)
            return [Session.from_dict(s) for s in data]
        except Exception:
            return []

    def _save_sessions(self, sessions: list[Session]) -> None:
        """Save sessions to file."""
        self.sessions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.sessions_file, "w") as f:
            json.dump([s.to_dict() for s in sessions], f, indent=2)

    def start_session(self, metadata: dict[str, Any] | None = None) -> Session:
        """Start a new session.

        Args:
            metadata: Optional session metadata

        Returns:
            The new session
        """
        session = Session(
            id=generate_session_id(),
            project_path=str(self.project_path) if self.project_path else "",
            started_at=get_timestamp(),
            metadata=metadata or {},
        )

        sessions = self._load_sessions()
        sessions.insert(0, session)

        # Keep only last 100 sessions
        sessions = sessions[:100]

        self._save_sessions(sessions)
        self._current_session = session

        return session

    def end_session(self, session_id: str | None = None) -> Session | None:
        """End a session.

        Args:
            session_id: Optional session ID (uses current if not provided)

        Returns:
            The ended session or None
        """
        sessions = self._load_sessions()

        target_id = session_id or (self._current_session.id if self._current_session else None)
        if not target_id:
            return None

        for session in sessions:
            if session.id == target_id:
                session.ended_at = get_timestamp()
                self._save_sessions(sessions)

                if self._current_session and self._current_session.id == target_id:
                    self._current_session = None

                return session

        return None

    def get_current_session(self) -> Session | None:
        """Get the current session."""
        return self._current_session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        sessions = self._load_sessions()
        for session in sessions:
            if session.id == session_id:
                return session
        return None

    def get_last_session(self) -> Session | None:
        """Get the most recent session."""
        sessions = self._load_sessions()
        return sessions[0] if sessions else None

    def list_sessions(self, limit: int = 10) -> list[Session]:
        """List recent sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of sessions, most recent first
        """
        sessions = self._load_sessions()
        return sessions[:limit]

    def add_summary(
        self,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        """Add a session summary.

        Args:
            content: Summary content
            session_id: Optional session ID (uses current if not provided)
            metadata: Optional additional metadata

        Returns:
            The created memory
        """
        target_session = None
        target_id = session_id or (self._current_session.id if self._current_session else None)

        if target_id:
            target_session = self.get_session(target_id)

        # Build metadata
        memory_metadata = metadata or {}
        if target_session:
            memory_metadata["session_id"] = target_session.id

        # Save as memory
        memory = self.store.save(
            content=content,
            category="session_summary",
            scope="project",
            source="auto_session",
            metadata=memory_metadata,
        )

        # Add to vector store
        if self.vector_store and self.vector_store.is_enabled():
            self.vector_store.add(
                memory_id=memory.id,
                content=content,
                category="session_summary",
                scope="project",
                groups=None,
            )

        # Update session summary count
        if target_session:
            sessions = self._load_sessions()
            for session in sessions:
                if session.id == target_session.id:
                    session.summary_count += 1
                    break
            self._save_sessions(sessions)

        return memory

    def get_session_summaries(
        self,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Get summaries for a session.

        Args:
            session_id: Optional session ID (gets all if not provided)
            limit: Maximum number of summaries

        Returns:
            List of summary memories
        """
        summaries = self.store.list(
            scope="project",
            category="session_summary",
            limit=limit * 2,  # Get extra for filtering
        )

        if session_id:
            summaries = [s for s in summaries if s.metadata.get("session_id") == session_id]

        return summaries[:limit]

    def load_last_session_context(self) -> list[Memory]:
        """Load memories from the last session.

        Returns:
            List of memories from the last session
        """
        last_session = self.get_last_session()
        if not last_session:
            return []

        return self.get_session_summaries(last_session.id)

    def should_summarize(self, message_count: int) -> bool:
        """Check if it's time to create a summary based on message count.

        Args:
            message_count: Current message count in session

        Returns:
            True if a summary should be created
        """
        if not self.config.autosave.session_summary:
            return False

        interval = self.config.autosave.summary_interval_messages
        return message_count > 0 and message_count % interval == 0

    def cleanup_old_sessions(self, keep_days: int = 90) -> int:
        """Remove old session records.

        Args:
            keep_days: Number of days to keep sessions

        Returns:
            Number of sessions removed
        """
        from datetime import timedelta

        sessions = self._load_sessions()
        cutoff = get_timestamp() - timedelta(days=keep_days)

        original_count = len(sessions)
        sessions = [s for s in sessions if s.started_at >= cutoff]

        self._save_sessions(sessions)
        return original_count - len(sessions)
