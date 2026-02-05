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
    shared_groups: list[str]  # List of group names this memory is shared with
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
            "shared_groups": self.shared_groups,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Memory:
        """Create Memory from database row."""
        # Handle both old schema (11 columns) and new schema (12 columns)
        if len(row) >= 12:
            shared_groups = deserialize_metadata(row[11]) if row[11] else []
        else:
            shared_groups = []

        return cls(
            id=row[0],
            content=row[1],
            category=row[2],
            scope=row[3],
            project_path=row[4],
            pinned=bool(row[5]),
            shared_groups=shared_groups if isinstance(shared_groups, list) else [],
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
                metadata TEXT DEFAULT '{}',
                shared_groups TEXT DEFAULT '[]'
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

        # Migration: Add shared_groups column if it doesn't exist
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN shared_groups TEXT DEFAULT '[]'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

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
        shared_groups: list[str] | None = None,
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
            shared_groups: List of group names to share this memory with

        Returns:
            The created Memory object
        """
        memory_id = generate_memory_id()
        now = get_timestamp()
        category = normalize_category(category, content)
        shared_groups = shared_groups or []

        project_path_str = str(self.project_path) if self.project_path else None

        conn = self._get_conn(scope)
        conn.execute(
            """
            INSERT INTO memories 
            (id, content, category, scope, project_path, pinned, 
             created_at, updated_at, expires_at, source, metadata, shared_groups)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                serialize_metadata(shared_groups),
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
            shared_groups=shared_groups,
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

    def share(
        self,
        memory_id: str,
        group_names: list[str],
        scope: str = "project",
    ) -> Memory | None:
        """Share a memory with one or more groups.

        Args:
            memory_id: ID of the memory to share
            group_names: List of group names to share with
            scope: "project" or "global"

        Returns:
            Updated memory or None if not found
        """
        memory = self.get(memory_id, scope)
        if memory is None:
            return None

        # Merge with existing shared groups
        current_groups = set(memory.shared_groups)
        current_groups.update(group_names)
        new_groups = sorted(current_groups)

        conn = self._get_conn(scope)
        now = get_timestamp()

        conn.execute(
            "UPDATE memories SET shared_groups = ?, updated_at = ? WHERE id = ?",
            (serialize_metadata(new_groups), now.isoformat(), memory_id),
        )
        conn.commit()

        return self.get(memory_id, scope)

    def unshare(
        self,
        memory_id: str,
        group_names: list[str] | None = None,
        scope: str = "project",
    ) -> Memory | None:
        """Remove a memory from one or more groups.

        Args:
            memory_id: ID of the memory to unshare
            group_names: List of group names to remove from (None = remove from all)
            scope: "project" or "global"

        Returns:
            Updated memory or None if not found
        """
        memory = self.get(memory_id, scope)
        if memory is None:
            return None

        if group_names is None:
            # Remove from all groups
            new_groups: list[str] = []
        else:
            # Remove only specified groups
            new_groups = [g for g in memory.shared_groups if g not in group_names]

        conn = self._get_conn(scope)
        now = get_timestamp()

        conn.execute(
            "UPDATE memories SET shared_groups = ?, updated_at = ? WHERE id = ?",
            (serialize_metadata(new_groups), now.isoformat(), memory_id),
        )
        conn.commit()

        return self.get(memory_id, scope)

    def promote_to_global(
        self,
        memory_id: str,
        from_project: Path | None = None,
    ) -> Memory | None:
        """Move a memory from project scope to global scope.

        Args:
            memory_id: ID of the memory to promote
            from_project: Project path (uses current project if None)

        Returns:
            The new global memory or None if not found
        """
        # Use specified project or current project
        if from_project is not None:
            source_store = MemoryStore(self.config, from_project)
        else:
            source_store = self

        # Get memory from project
        memory = source_store.get(memory_id, "project")
        if memory is None:
            return None

        # Save to global
        global_memory = self.save(
            content=memory.content,
            category=memory.category,
            scope="global",
            pinned=memory.pinned,
            source=memory.source,
            metadata=memory.metadata,
            shared_groups=memory.shared_groups,
        )

        # Delete from project
        source_store.delete(memory_id, "project")

        return global_memory

    def unpromote_to_project(
        self,
        memory_id: str,
        to_project: Path,
    ) -> Memory | None:
        """Move a memory from global scope to a specific project.

        Args:
            memory_id: ID of the global memory to unpromote
            to_project: Target project path

        Returns:
            The new project memory or None if not found
        """
        # Get memory from global
        memory = self.get(memory_id, "global")
        if memory is None:
            return None

        # Create store for target project
        target_store = MemoryStore(self.config, to_project)

        # Save to project
        project_memory = target_store.save(
            content=memory.content,
            category=memory.category,
            scope="project",
            pinned=memory.pinned,
            source=memory.source,
            metadata=memory.metadata,
            shared_groups=memory.shared_groups,
        )

        # Delete from global
        self.delete(memory_id, "global")

        return project_memory

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

    # ─────────────────────────────────────────────────────────────
    # CROSS-PROJECT METHODS (for user visibility, not agents)
    # ─────────────────────────────────────────────────────────────

    def list_all_projects(
        self,
        category: str | None = None,
        pinned_only: bool = False,
        limit_per_project: int = 50,
        include_global: bool = True,
    ) -> list[tuple[Path | None, list[Memory]]]:
        """
        List memories from all projects.

        This is for USER visibility across projects, not for agents.
        Agents should only access current project + global.

        Args:
            category: Filter by category
            pinned_only: Only return pinned memories
            limit_per_project: Max memories per project
            include_global: Include global memories

        Returns:
            List of (project_path, memories) tuples.
            project_path is None for global memories.
        """
        results: list[tuple[Path | None, list[Memory]]] = []

        # Include global memories first
        if include_global:
            global_memories = self._query_db_file(
                self.global_db_path,
                category=category,
                pinned_only=pinned_only,
                limit=limit_per_project,
            )
            if global_memories:
                results.append((None, global_memories))

        # Scan all project directories
        if self.config.projects_path.exists():
            for project_dir in sorted(self.config.projects_path.iterdir()):
                if not project_dir.is_dir():
                    continue

                db_path = project_dir / "memories.db"
                if not db_path.exists():
                    continue

                # Resolve original project path
                ref_file = project_dir / ".project_path"
                if ref_file.exists():
                    original_path = Path(ref_file.read_text().strip())
                else:
                    original_path = project_dir

                memories = self._query_db_file(
                    db_path,
                    category=category,
                    pinned_only=pinned_only,
                    limit=limit_per_project,
                )
                if memories:
                    results.append((original_path, memories))

        return results

    def search_all_projects(
        self,
        query: str,
        limit_per_project: int = 10,
        include_global: bool = True,
    ) -> list[tuple[Path | None, list[Memory]]]:
        """
        Search memories across all projects by keyword.

        This is for USER visibility across projects, not for agents.
        Agents should only access current project + global.

        Args:
            query: Search query
            limit_per_project: Max results per project
            include_global: Include global memories

        Returns:
            List of (project_path, memories) tuples.
            project_path is None for global memories.
        """
        results: list[tuple[Path | None, list[Memory]]] = []

        # Search global memories first
        if include_global:
            global_memories = self._search_db_file(
                self.global_db_path,
                query=query,
                limit=limit_per_project,
            )
            if global_memories:
                results.append((None, global_memories))

        # Scan all project directories
        if self.config.projects_path.exists():
            for project_dir in sorted(self.config.projects_path.iterdir()):
                if not project_dir.is_dir():
                    continue

                db_path = project_dir / "memories.db"
                if not db_path.exists():
                    continue

                # Resolve original project path
                ref_file = project_dir / ".project_path"
                if ref_file.exists():
                    original_path = Path(ref_file.read_text().strip())
                else:
                    original_path = project_dir

                memories = self._search_db_file(
                    db_path,
                    query=query,
                    limit=limit_per_project,
                )
                if memories:
                    results.append((original_path, memories))

        return results

    def get_all_project_stats(self) -> list[dict[str, Any]]:
        """
        Get statistics for all tracked projects.

        Returns:
            List of dicts with project_path, memory_count, last_updated
        """
        stats: list[dict[str, Any]] = []

        if not self.config.projects_path.exists():
            return stats

        for project_dir in sorted(self.config.projects_path.iterdir()):
            if not project_dir.is_dir():
                continue

            db_path = project_dir / "memories.db"
            if not db_path.exists():
                continue

            # Resolve original project path
            ref_file = project_dir / ".project_path"
            if ref_file.exists():
                original_path = Path(ref_file.read_text().strip())
            else:
                original_path = project_dir

            # Get stats from database
            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute("SELECT COUNT(*) FROM memories")
                count = cursor.fetchone()[0]

                cursor = conn.execute("SELECT MAX(updated_at) FROM memories")
                last_updated = cursor.fetchone()[0]
                conn.close()

                stats.append(
                    {
                        "project_path": original_path,
                        "memory_count": count,
                        "last_updated": parse_timestamp(last_updated) if last_updated else None,
                    }
                )
            except Exception:
                # Skip projects with corrupted databases
                continue

        return stats

    def _query_db_file(
        self,
        db_path: Path,
        category: str | None = None,
        pinned_only: bool = False,
        limit: int = 50,
    ) -> list[Memory]:
        """Query a specific database file."""
        if not db_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(db_path))
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
            conn.close()

            # Filter expired
            return [m for m in memories if not is_expired(m.expires_at)]
        except Exception:
            return []

    def _search_db_file(
        self,
        db_path: Path,
        query: str,
        limit: int = 10,
    ) -> list[Memory]:
        """Search a specific database file by keyword."""
        if not db_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(db_path))
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
            conn.close()

            # Filter expired
            return [m for m in memories if not is_expired(m.expires_at)]
        except Exception:
            return []
