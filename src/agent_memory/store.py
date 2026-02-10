"""SQLite-based memory store for metadata."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_memory.config import Config, find_descendant_project_paths, get_project_path
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
    scope: str  # "project", "group", or "global"
    project_path: str | None
    pinned: bool
    groups: list[str]  # Owner groups (only used when scope="group")
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    source: str  # "user_explicit", "auto_task", "auto_session"
    metadata: dict[str, Any]
    access_count: int = 0
    last_accessed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "scope": self.scope,
            "project_path": self.project_path,
            "pinned": self.pinned,
            "groups": self.groups,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "source": self.source,
            "metadata": self.metadata,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at.isoformat()
            if self.last_accessed_at
            else None,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Memory:
        """Create Memory from database row."""
        # Handle schema with groups column (index 11)
        if len(row) >= 12:
            groups = deserialize_metadata(row[11]) if row[11] else []
        else:
            groups = []

        # Handle access tracking columns (index 12, 13)
        access_count = row[12] if len(row) > 12 and row[12] is not None else 0
        last_accessed_at = parse_timestamp(row[13]) if len(row) > 13 and row[13] else None

        return cls(
            id=row[0],
            content=row[1],
            category=row[2],
            scope=row[3],
            project_path=row[4],
            pinned=bool(row[5]),
            groups=groups if isinstance(groups, list) else [],
            created_at=parse_timestamp(row[6]),
            updated_at=parse_timestamp(row[7]),
            expires_at=parse_timestamp(row[8]) if row[8] else None,
            source=row[9],
            metadata=deserialize_metadata(row[10]),
            access_count=access_count,
            last_accessed_at=last_accessed_at,
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
        """Get connection for scope.

        Note: 'group' scope uses the global database.
        """
        if scope in ("global", "group"):
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
                groups TEXT DEFAULT '[]',
                access_count INTEGER DEFAULT 0,
                last_accessed_at TEXT
            )
        """)

        # Run migrations BEFORE creating indexes on new columns
        self._migrate_groups_column(conn)
        self._migrate_access_tracking(conn)

        # Create indexes (safe to run after migrations)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_pinned ON memories(pinned)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_access ON memories(access_count)
        """)

        conn.commit()

    def _migrate_groups_column(self, conn: sqlite3.Connection) -> None:
        """Migrate from shared_groups to groups column and update scopes."""
        # Check if old shared_groups column exists
        cursor = conn.execute("PRAGMA table_info(memories)")
        columns = {row[1] for row in cursor.fetchall()}

        if "shared_groups" in columns and "groups" not in columns:
            # Add new groups column
            conn.execute("ALTER TABLE memories ADD COLUMN groups TEXT DEFAULT '[]'")
            # Copy data from shared_groups to groups
            conn.execute("UPDATE memories SET groups = shared_groups")
            # Update scope to 'group' for memories with non-empty groups
            conn.execute("""
                UPDATE memories 
                SET scope = 'group' 
                WHERE groups != '[]' AND groups IS NOT NULL AND groups != ''
            """)
            conn.commit()
        elif "groups" not in columns:
            # Fresh install - just add groups column
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN groups TEXT DEFAULT '[]'")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

    def _migrate_access_tracking(self, conn: sqlite3.Connection) -> None:
        """Add access tracking columns if they don't exist."""
        cursor = conn.execute("PRAGMA table_info(memories)")
        columns = {row[1] for row in cursor.fetchall()}

        if "access_count" not in columns:
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN access_count INTEGER DEFAULT 0")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

        if "last_accessed_at" not in columns:
            try:
                conn.execute("ALTER TABLE memories ADD COLUMN last_accessed_at TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

    def record_access(self, memory_id: str, scope: str = "project") -> None:
        """Record an access to a memory (increment count, update timestamp)."""
        conn = self._get_conn(scope)
        conn.execute(
            """
            UPDATE memories 
            SET access_count = access_count + 1,
                last_accessed_at = ?
            WHERE id = ?
            """,
            (get_timestamp().isoformat(), memory_id),
        )
        conn.commit()

    def record_access_batch(self, memory_ids: list[str], scope: str = "project") -> None:
        """Record access to multiple memories."""
        if not memory_ids:
            return
        conn = self._get_conn(scope)
        now = get_timestamp().isoformat()
        for memory_id in memory_ids:
            conn.execute(
                """
                UPDATE memories 
                SET access_count = access_count + 1,
                    last_accessed_at = ?
                WHERE id = ?
                """,
                (now, memory_id),
            )
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
        groups: list[str] | None = None,
    ) -> Memory:
        """Save a new memory.

        Args:
            content: The memory content
            category: Memory category (auto-detected if not provided)
            scope: "project", "group", or "global"
            pinned: Whether to pin the memory
            source: Source of the memory
            metadata: Additional metadata
            expires_at: Optional expiration datetime
            groups: Owner groups (required for scope="group", ignored otherwise)

        Returns:
            The created Memory object
        """
        memory_id = generate_memory_id()
        now = get_timestamp()
        category = normalize_category(category, content)
        groups = groups or []

        # Validate scope
        if scope not in ("project", "group", "global"):
            raise ValueError(f"Invalid scope: {scope}. Must be 'project', 'group', or 'global'")

        # Group scope requires groups
        if scope == "group" and not groups:
            raise ValueError("Group scope requires at least one group")

        project_path_str = str(self.project_path) if self.project_path else None

        # Group and global scopes use global DB
        db_scope = "global" if scope in ("group", "global") else "project"
        conn = self._get_conn(db_scope)
        conn.execute(
            """
            INSERT INTO memories 
            (id, content, category, scope, project_path, pinned, 
             created_at, updated_at, expires_at, source, metadata, groups)
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
                serialize_metadata(groups),
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
            groups=groups,
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

        # Filter by scope when using global DB (contains both 'group' and 'global' scopes)
        if scope in ("group", "global"):
            query += " AND scope = ?"
            params.append(scope)

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

    def list_by_group(
        self,
        group_name: str | None = None,
        pinned_only: bool = False,
        category: str | None = None,
        limit: int = 50,
        include_expired: bool = False,
    ) -> list[Memory]:
        """List group-scoped memories, optionally filtered by owner group name.

        Args:
            group_name: Filter by owner group name. None = all group-scoped memories.
                       Use "all" to explicitly get all groups.
            pinned_only: Only return pinned memories.
            category: Filter by category.
            limit: Maximum number of results.
            include_expired: Include expired memories.

        Returns:
            List of group-scoped memories.
        """
        # Group memories are stored in global DB with scope="group"
        conn = self._get_conn("global")

        query = "SELECT * FROM memories WHERE scope = 'group'"
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

        # Filter by group name if specified (groups is a list field)
        if group_name and group_name.lower() != "all":
            memories = [m for m in memories if group_name in m.groups]

        if not include_expired:
            memories = [m for m in memories if not is_expired(m.expires_at)]

        return memories

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

    def search_with_groups(
        self,
        query: str,
        include_project: bool = True,
        include_global: bool = True,
        include_groups: list[str] | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Search memories across multiple scopes including groups.

        Args:
            query: Search query string.
            include_project: Include project-scoped memories.
            include_global: Include global-scoped memories.
            include_groups: List of group names to include. Use ["all"] for all groups.
            limit: Maximum results per scope.

        Returns:
            Combined list of matching memories from all requested scopes.
        """
        results: list[Memory] = []
        seen_ids: set[str] = set()

        def add_unique(memories: list[Memory]) -> None:
            for m in memories:
                if m.id not in seen_ids and not is_expired(m.expires_at):
                    results.append(m)
                    seen_ids.add(m.id)

        # Search project scope
        if include_project and self.project_path is not None:
            add_unique(self.search_keyword(query, "project", limit))

        # Search global scope
        if include_global:
            add_unique(self.search_keyword(query, "global", limit))

        # Search group scope
        if include_groups:
            group_memories = self.list_by_group(limit=limit * 2)
            # Filter by query
            query_lower = query.lower()
            matching = [m for m in group_memories if query_lower in m.content.lower()]

            # Filter by group names if not "all"
            if "all" not in [g.lower() for g in include_groups]:
                matching = [m for m in matching if any(g in m.groups for g in include_groups)]

            add_unique(matching)

        # Sort by created_at descending and limit
        results.sort(key=lambda m: m.created_at, reverse=True)
        return results[:limit]

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

    def add_groups(
        self,
        memory_id: str,
        group_names: list[str],
    ) -> Memory | None:
        """Add owner groups to a group-scoped memory.

        Args:
            memory_id: ID of the memory
            group_names: List of group names to add

        Returns:
            Updated memory or None if not found
        """
        memory = self.get_by_id(memory_id)
        if memory is None:
            return None

        if memory.scope != "group":
            raise ValueError("Can only add groups to group-scoped memories")

        # Merge with existing groups
        current_groups = set(memory.groups)
        current_groups.update(group_names)
        new_groups = sorted(current_groups)

        conn = self._get_conn("global")  # Group scope uses global DB
        now = get_timestamp()

        conn.execute(
            "UPDATE memories SET groups = ?, updated_at = ? WHERE id = ?",
            (serialize_metadata(new_groups), now.isoformat(), memory_id),
        )
        conn.commit()

        return self.get_by_id(memory_id)

    def remove_groups(
        self,
        memory_id: str,
        group_names: list[str],
    ) -> Memory | None:
        """Remove owner groups from a group-scoped memory.

        Args:
            memory_id: ID of the memory
            group_names: List of group names to remove

        Returns:
            Updated memory or None if not found
        """
        memory = self.get_by_id(memory_id)
        if memory is None:
            return None

        if memory.scope != "group":
            raise ValueError("Can only remove groups from group-scoped memories")

        new_groups = [g for g in memory.groups if g not in group_names]

        if not new_groups:
            raise ValueError(
                "Cannot remove all groups from a group-scoped memory. Use set_scope to change to global."
            )

        conn = self._get_conn("global")
        now = get_timestamp()

        conn.execute(
            "UPDATE memories SET groups = ?, updated_at = ? WHERE id = ?",
            (serialize_metadata(new_groups), now.isoformat(), memory_id),
        )
        conn.commit()

        return self.get_by_id(memory_id)

    def set_groups(
        self,
        memory_id: str,
        group_names: list[str],
    ) -> Memory | None:
        """Set owner groups for a group-scoped memory (replaces all).

        Args:
            memory_id: ID of the memory
            group_names: List of group names (replaces existing)

        Returns:
            Updated memory or None if not found
        """
        memory = self.get_by_id(memory_id)
        if memory is None:
            return None

        if memory.scope != "group":
            raise ValueError("Can only set groups on group-scoped memories")

        if not group_names:
            raise ValueError(
                "Cannot set empty groups on group-scoped memory. Use set_scope to change to global."
            )

        conn = self._get_conn("global")
        now = get_timestamp()

        conn.execute(
            "UPDATE memories SET groups = ?, updated_at = ? WHERE id = ?",
            (serialize_metadata(sorted(group_names)), now.isoformat(), memory_id),
        )
        conn.commit()

        return self.get_by_id(memory_id)

    def set_scope(
        self,
        memory_id: str,
        new_scope: str,
        groups: list[str] | None = None,
    ) -> Memory | None:
        """Change the scope of a memory.

        Args:
            memory_id: ID of the memory
            new_scope: New scope ("project", "group", or "global")
            groups: Required if new_scope is "group"

        Returns:
            Updated memory or None if not found
        """
        memory = self.get_by_id(memory_id)
        if memory is None:
            return None

        if new_scope not in ("project", "group", "global"):
            raise ValueError(f"Invalid scope: {new_scope}")

        if new_scope == "group" and not groups:
            raise ValueError("Group scope requires at least one group")

        # Determine source and target databases
        old_db = "global" if memory.scope in ("group", "global") else "project"
        new_db = "global" if new_scope in ("group", "global") else "project"

        if old_db == new_db:
            # Same database - just update scope and groups
            conn = self._get_conn(old_db)
            now = get_timestamp()
            new_groups = groups if new_scope == "group" else []
            conn.execute(
                "UPDATE memories SET scope = ?, groups = ?, updated_at = ? WHERE id = ?",
                (new_scope, serialize_metadata(new_groups), now.isoformat(), memory_id),
            )
            conn.commit()
            return self.get_by_id(memory_id)
        else:
            # Different databases - need to move the memory
            # Delete from old location
            self.delete(memory_id, old_db)
            # Save to new location
            return self.save(
                content=memory.content,
                category=memory.category,
                scope=new_scope,
                pinned=memory.pinned,
                source=memory.source,
                metadata=memory.metadata,
                groups=groups if new_scope == "group" else None,
            )

    def promote(
        self,
        memory_id: str,
        from_project: Path | None = None,
        to_group: list[str] | None = None,
    ) -> Memory | None:
        """Move a memory from project scope to global or group scope.

        Args:
            memory_id: ID of the memory to promote
            from_project: Project path (uses current project if None)
            to_group: If specified, promote to group scope with these owner groups.
                      If None, promote to global scope (true global).

        Returns:
            The new memory or None if not found
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

        # Determine target scope
        target_scope = "group" if to_group else "global"

        # Save to new scope
        new_memory = self.save(
            content=memory.content,
            category=memory.category,
            scope=target_scope,
            pinned=memory.pinned,
            source=memory.source,
            metadata=memory.metadata,
            groups=to_group,
        )

        # Delete from project
        source_store.delete(memory_id, "project")

        return new_memory

    def unpromote(
        self,
        memory_id: str,
        to_project: Path,
    ) -> Memory | None:
        """Move a memory from global or group scope to a specific project.

        Args:
            memory_id: ID of the memory to unpromote
            to_project: Target project path

        Returns:
            The new project memory or None if not found
        """
        # Get memory from global DB (could be 'global' or 'group' scope)
        memory = self.get(memory_id, "global")
        if memory is None:
            return None

        if memory.scope not in ("global", "group"):
            raise ValueError("Can only unpromote global or group-scoped memories")

        # Create store for target project
        target_store = MemoryStore(self.config, to_project)

        # Save to project (groups are not preserved - project scope doesn't use groups)
        project_memory = target_store.save(
            content=memory.content,
            category=memory.category,
            scope="project",
            pinned=memory.pinned,
            source=memory.source,
            metadata=memory.metadata,
        )

        # Delete from global DB
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

    def get_most_accessed(self, scope: str = "project", limit: int = 10) -> list[Memory]:
        """Get most frequently accessed memories.

        Args:
            scope: Memory scope to query
            limit: Maximum number of results

        Returns:
            List of memories ordered by access_count DESC
        """
        conn = self._get_conn(scope)

        query = "SELECT * FROM memories WHERE access_count > 0"
        params: list[Any] = []

        if scope in ("group", "global"):
            query += " AND scope = ?"
            params.append(scope)

        query += " ORDER BY access_count DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        return [Memory.from_row(row) for row in cursor.fetchall()]

    def get_pin_candidates(
        self, scope: str = "project", min_access: int = 3, limit: int = 10
    ) -> list[Memory]:
        """Get high-access memories that are not pinned (candidates for pinning).

        Args:
            scope: Memory scope to query
            min_access: Minimum access_count to qualify
            limit: Maximum number of results

        Returns:
            List of unpinned memories with high access counts
        """
        conn = self._get_conn(scope)

        query = "SELECT * FROM memories WHERE access_count >= ? AND pinned = 0"
        params: list[Any] = [min_access]

        if scope in ("group", "global"):
            query += " AND scope = ?"
            params.append(scope)

        query += " ORDER BY access_count DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        return [Memory.from_row(row) for row in cursor.fetchall()]

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
    # DESCENDANT PROJECT METHODS (hierarchical lookup)
    # ─────────────────────────────────────────────────────────────

    @property
    def _descendant_db_paths(self) -> list[tuple[Path, Path]]:
        """Get (original_project_path, db_path) for descendant projects.

        Cached on first access. Only returns descendants that have a memories.db.
        """
        if not hasattr(self, "_cached_descendant_db_paths"):
            if self.project_path is None:
                self._cached_descendant_db_paths: list[tuple[Path, Path]] = []
            else:
                descendants = find_descendant_project_paths(self.config, self.project_path)
                self._cached_descendant_db_paths = [
                    (orig, storage / "memories.db")
                    for orig, storage in descendants
                    if (storage / "memories.db").exists()
                ]
        return self._cached_descendant_db_paths

    def list_with_descendants(
        self,
        category: str | None = None,
        pinned_only: bool = False,
        limit: int = 50,
        include_expired: bool = False,
    ) -> list[Memory]:
        """List project memories including those from descendant projects.

        Queries the current project DB plus all descendant project DBs,
        deduplicates by ID, and sorts by created_at DESC.

        Args:
            category: Filter by category
            pinned_only: Only return pinned memories
            limit: Maximum number of results
            include_expired: Include expired memories

        Returns:
            Merged, deduplicated list of memories
        """
        seen_ids: set[str] = set()
        all_memories: list[Memory] = []

        # Current project memories first
        try:
            current = self.list(
                scope="project",
                category=category,
                pinned_only=pinned_only,
                limit=limit,
                include_expired=include_expired,
            )
            for m in current:
                if m.id not in seen_ids:
                    all_memories.append(m)
                    seen_ids.add(m.id)
        except Exception:
            pass

        # Descendant project memories
        for _orig_path, db_path in self._descendant_db_paths:
            descendant_memories = self._query_db_file(
                db_path,
                category=category,
                pinned_only=pinned_only,
                limit=limit,
            )
            for m in descendant_memories:
                if m.id not in seen_ids:
                    all_memories.append(m)
                    seen_ids.add(m.id)

        # Sort by created_at DESC and limit
        all_memories.sort(key=lambda m: m.created_at, reverse=True)
        return all_memories[:limit]

    def search_with_descendants(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Memory]:
        """Search project memories including descendant projects by keyword.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            Merged, deduplicated list of matching memories
        """
        seen_ids: set[str] = set()
        all_memories: list[Memory] = []

        # Current project
        try:
            current = self.search_keyword(query, "project", limit)
            for m in current:
                if m.id not in seen_ids:
                    all_memories.append(m)
                    seen_ids.add(m.id)
        except Exception:
            pass

        # Descendant projects
        for _orig_path, db_path in self._descendant_db_paths:
            descendant_memories = self._search_db_file(
                db_path,
                query=query,
                limit=limit,
            )
            for m in descendant_memories:
                if m.id not in seen_ids:
                    all_memories.append(m)
                    seen_ids.add(m.id)

        # Sort by created_at DESC and limit
        all_memories.sort(key=lambda m: m.created_at, reverse=True)
        return all_memories[:limit]

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
