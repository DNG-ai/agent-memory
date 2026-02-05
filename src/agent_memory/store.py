"""SQLite-based memory store for metadata."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_memory.config import Config, get_project_path
from agent_memory.utils import (
    deserialize_metadata,
    generate_memory_id,
    get_timestamp,
    is_expired,
    normalize_category,
    parse_timestamp,
    serialize_metadata,
)


@dataclass
class Memory:
    """A memory record."""

    id: str
    content: str
    category: str
    scope: str  # "project" or "global"
    project_path: str | None
    pinned: bool
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    source: str  # "user_explicit", "auto_task", "auto_session"
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "scope": self.scope,
            "project_path": self.project_path,
            "pinned": self.pinned,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Memory:
        """Create Memory from database row."""
        return cls(
            id=row[0],
            content=row[1],
            category=row[2],
            scope=row[3],
            project_path=row[4],
            pinned=bool(row[5]),
            created_at=parse_timestamp(row[6]),
            updated_at=parse_timestamp(row[7]),
            expires_at=parse_timestamp(row[8]) if row[8] else None,
            source=row[9],
            metadata=deserialize_metadata(row[10]),
        )


class MemoryStore:
    """SQLite-based memory store."""

    def __init__(self, config: Config, project_path: Path | None = None):
        """Initialize the memory store.

        Args:
            config: Configuration object
            project_path: Optional project path for project-scoped operations
        """
        self.config = config
        self.project_path = project_path
        self._global_conn: sqlite3.Connection | None = None
        self._project_conn: sqlite3.Connection | None = None

    @property
    def global_db_path(self) -> Path:
        """Path to global database."""
        return self.config.global_path / "memories.db"

    @property
    def project_db_path(self) -> Path | None:
        """Path to project database."""
        if self.project_path is None:
            return None
        project_storage = get_project_path(self.config, self.project_path)
        return project_storage / "memories.db"

    def _get_global_conn(self) -> sqlite3.Connection:
        """Get or create global database connection."""
        if self._global_conn is None:
            self._global_conn = sqlite3.connect(str(self.global_db_path))
            self._init_db(self._global_conn)
        return self._global_conn

    def _get_project_conn(self) -> sqlite3.Connection:
        """Get or create project database connection."""
        if self.project_db_path is None:
            raise ValueError("No project path set")
        if self._project_conn is None:
            self._project_conn = sqlite3.connect(str(self.project_db_path))
            self._init_db(self._project_conn)
        return self._project_conn

    def _get_conn(self, scope: str) -> sqlite3.Connection:
        """Get connection for scope."""
        if scope == "global":
            return self._get_global_conn()
        return self._get_project_conn()

    def _init_db(self, conn: sqlite3.Connection) -> None:
        """Initialize database schema."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                scope TEXT NOT NULL,
                project_path TEXT,
                pinned INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                source TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_pinned ON memories(pinned)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)
        """)
        conn.commit()

    def save(
        self,
        content: str,
        category: str | None = None,
        scope: str = "project",
        pinned: bool = False,
        source: str = "user_explicit",
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> Memory:
        """Save a new memory.

        Args:
            content: The memory content
            category: Memory category (auto-detected if not provided)
            scope: "project" or "global"
            pinned: Whether to pin the memory
            source: Source of the memory
            metadata: Additional metadata
            expires_at: Optional expiration datetime

        Returns:
            The created Memory object
        """
        memory_id = generate_memory_id()
        now = get_timestamp()
        category = normalize_category(category, content)

        project_path_str = str(self.project_path) if self.project_path else None

        conn = self._get_conn(scope)
        conn.execute(
            """
            INSERT INTO memories 
            (id, content, category, scope, project_path, pinned, 
             created_at, updated_at, expires_at, source, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                content,
                category,
                scope,
                project_path_str,
                int(pinned),
                now.isoformat(),
                now.isoformat(),
                expires_at.isoformat() if expires_at else None,
                source,
                serialize_metadata(metadata),
            ),
        )
        conn.commit()

        return Memory(
            id=memory_id,
            content=content,
            category=category,
            scope=scope,
            project_path=project_path_str,
            pinned=pinned,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            source=source,
            metadata=metadata or {},
        )

    def get(self, memory_id: str, scope: str = "project") -> Memory | None:
        """Get a memory by ID."""
        conn = self._get_conn(scope)
        cursor = conn.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Memory.from_row(row)

    def get_by_id(self, memory_id: str) -> Memory | None:
        """Get a memory by ID, searching both project and global."""
        # Try project first
        if self.project_path is not None:
            memory = self.get(memory_id, "project")
            if memory:
                return memory
        # Try global
        return self.get(memory_id, "global")

    def list(
        self,
        scope: str = "project",
        category: str | None = None,
        pinned_only: bool = False,
        limit: int = 50,
        include_expired: bool = False,
    ) -> list[Memory]:
        """List memories with optional filters."""
        conn = self._get_conn(scope)

        query = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if pinned_only:
            query += " AND pinned = 1"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        memories = [Memory.from_row(row) for row in cursor.fetchall()]

        if not include_expired:
            memories = [m for m in memories if not is_expired(m.expires_at)]

        return memories

    def list_pinned(self, scope: str = "project") -> list[Memory]:
        """List all pinned memories."""
        return self.list(scope=scope, pinned_only=True, limit=100)

    def search_keyword(
        self,
        query: str,
        scope: str = "project",
        limit: int = 10,
    ) -> list[Memory]:
        """Search memories by keyword."""
        conn = self._get_conn(scope)
        cursor = conn.execute(
            """
            SELECT * FROM memories 
            WHERE content LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        memories = [Memory.from_row(row) for row in cursor.fetchall()]
        return [m for m in memories if not is_expired(m.expires_at)]

    def update(
        self,
        memory_id: str,
        scope: str = "project",
        content: str | None = None,
        category: str | None = None,
        pinned: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory | None:
        """Update a memory."""
        memory = self.get(memory_id, scope)
        if memory is None:
            return None

        conn = self._get_conn(scope)
        now = get_timestamp()

        updates = ["updated_at = ?"]
        params: list[Any] = [now.isoformat()]

        if content is not None:
            updates.append("content = ?")
            params.append(content)

        if category is not None:
            updates.append("category = ?")
            params.append(category)

        if pinned is not None:
            updates.append("pinned = ?")
            params.append(int(pinned))

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(serialize_metadata(metadata))

        params.append(memory_id)

        conn.execute(
            f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()

        return self.get(memory_id, scope)

    def pin(self, memory_id: str, scope: str = "project") -> Memory | None:
        """Pin a memory."""
        return self.update(memory_id, scope, pinned=True)

    def unpin(self, memory_id: str, scope: str = "project") -> Memory | None:
        """Unpin a memory."""
        return self.update(memory_id, scope, pinned=False)

    def delete(self, memory_id: str, scope: str = "project") -> bool:
        """Delete a memory."""
        conn = self._get_conn(scope)
        cursor = conn.execute(
            "DELETE FROM memories WHERE id = ?",
            (memory_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete_by_id(self, memory_id: str) -> bool:
        """Delete a memory by ID, searching both project and global."""
        # Try project first
        if self.project_path is not None:
            if self.delete(memory_id, "project"):
                return True
        # Try global
        return self.delete(memory_id, "global")

    def delete_matching(
        self,
        query: str,
        scope: str = "project",
    ) -> int:
        """Delete memories matching a search query."""
        conn = self._get_conn(scope)
        cursor = conn.execute(
            "DELETE FROM memories WHERE content LIKE ?",
            (f"%{query}%",),
        )
        conn.commit()
        return cursor.rowcount

    def cleanup_expired(self, scope: str = "project") -> int:
        """Remove expired memories."""
        conn = self._get_conn(scope)
        now = get_timestamp()
        cursor = conn.execute(
            """
            DELETE FROM memories 
            WHERE expires_at IS NOT NULL AND expires_at < ?
            """,
            (now.isoformat(),),
        )
        conn.commit()
        return cursor.rowcount

    def reset(self, scope: str = "project") -> int:
        """Delete all memories in scope."""
        conn = self._get_conn(scope)
        cursor = conn.execute("DELETE FROM memories")
        conn.commit()
        return cursor.rowcount

    def count(self, scope: str = "project") -> int:
        """Count memories in scope."""
        conn = self._get_conn(scope)
        cursor = conn.execute("SELECT COUNT(*) FROM memories")
        return cursor.fetchone()[0]

    def close(self) -> None:
        """Close database connections."""
        if self._global_conn:
            self._global_conn.close()
            self._global_conn = None
        if self._project_conn:
            self._project_conn.close()
            self._project_conn = None

    def __enter__(self) -> MemoryStore:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()
