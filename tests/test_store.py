"""Tests for the memory store."""

from __future__ import annotations

import pytest

from agent_memory.config import Config
from agent_memory.store import Memory, MemoryStore


class TestMemoryStore:
    """Tests for MemoryStore."""

    def test_save_memory(self, store: MemoryStore) -> None:
        """Test saving a memory."""
        memory = store.save(
            content="Test memory content",
            category="factual",
            scope="project",
        )

        assert memory.id.startswith("mem_")
        assert memory.content == "Test memory content"
        assert memory.category == "factual"
        assert memory.scope == "project"
        assert memory.pinned is False

    def test_save_memory_auto_category(self, store: MemoryStore) -> None:
        """Test auto-detection of memory category."""
        # Decision detection
        memory = store.save(
            content="User prefers functional components",
            scope="project",
        )
        assert memory.category == "decision"

        # Task history detection
        memory = store.save(
            content="Implemented the login feature",
            scope="project",
        )
        assert memory.category == "task_history"

        # Default to factual
        memory = store.save(
            content="The API uses REST",
            scope="project",
        )
        assert memory.category == "factual"

    def test_save_pinned_memory(self, store: MemoryStore) -> None:
        """Test saving a pinned memory."""
        memory = store.save(
            content="Critical information",
            pinned=True,
            scope="project",
        )

        assert memory.pinned is True

    def test_get_memory(self, store: MemoryStore) -> None:
        """Test getting a memory by ID."""
        saved = store.save(content="Test content", scope="project")

        retrieved = store.get(saved.id, "project")

        assert retrieved is not None
        assert retrieved.id == saved.id
        assert retrieved.content == saved.content

    def test_get_nonexistent_memory(self, store: MemoryStore) -> None:
        """Test getting a nonexistent memory."""
        memory = store.get("mem_nonexistent", "project")
        assert memory is None

    def test_list_memories(self, store: MemoryStore) -> None:
        """Test listing memories."""
        store.save(content="Memory 1", scope="project")
        store.save(content="Memory 2", scope="project")
        store.save(content="Memory 3", scope="project")

        memories = store.list("project")

        assert len(memories) == 3

    def test_list_memories_by_category(self, store: MemoryStore) -> None:
        """Test listing memories filtered by category."""
        store.save(content="Fact 1", category="factual", scope="project")
        store.save(content="User prefers X", category="decision", scope="project")
        store.save(content="Fact 2", category="factual", scope="project")

        factual = store.list("project", category="factual")
        decisions = store.list("project", category="decision")

        assert len(factual) == 2
        assert len(decisions) == 1

    def test_list_pinned_memories(self, store: MemoryStore) -> None:
        """Test listing only pinned memories."""
        store.save(content="Normal", scope="project")
        store.save(content="Pinned 1", pinned=True, scope="project")
        store.save(content="Pinned 2", pinned=True, scope="project")

        pinned = store.list_pinned("project")

        assert len(pinned) == 2
        assert all(m.pinned for m in pinned)

    def test_search_keyword(self, store: MemoryStore) -> None:
        """Test keyword search."""
        store.save(content="The API uses JWT tokens", scope="project")
        store.save(content="Database is PostgreSQL", scope="project")
        store.save(content="JWT tokens expire after 1 hour", scope="project")

        results = store.search_keyword("JWT", "project")

        assert len(results) == 2
        assert all("JWT" in m.content for m in results)

    def test_search_keyword_case_insensitive(self, store: MemoryStore) -> None:
        """Test that keyword search is case-insensitive."""
        store.save(content="The API uses JWT tokens", scope="project")
        store.save(content="Database is PostgreSQL", scope="project")
        store.save(content="jwt tokens expire after 1 hour", scope="project")

        # lowercase query should match uppercase content
        results = store.search_keyword("jwt", "project")
        assert len(results) == 2

        # uppercase query should match lowercase content
        results = store.search_keyword("JWT", "project")
        assert len(results) == 2

        # mixed case
        results = store.search_keyword("Jwt", "project")
        assert len(results) == 2

    def test_search_keyword_multi_term(self, store: MemoryStore) -> None:
        """Test that multi-term queries match all terms independently."""
        store.save(content="Use poetry to run tests in this project", scope="project")
        store.save(content="The poetry config is in pyproject.toml", scope="project")
        store.save(content="Run pytest for unit tests", scope="project")

        # Both terms must match
        results = store.search_keyword("poetry test", "project")
        assert len(results) == 1
        assert "poetry" in results[0].content.lower()
        assert "test" in results[0].content.lower()

        # Single term matches more
        results = store.search_keyword("poetry", "project")
        assert len(results) == 2

    def test_search_keyword_empty_query(self, store: MemoryStore) -> None:
        """Test that empty/whitespace queries return empty list."""
        store.save(content="Some content", scope="project")

        assert store.search_keyword("", "project") == []
        assert store.search_keyword("   ", "project") == []

    def test_update_memory(self, store: MemoryStore) -> None:
        """Test updating a memory."""
        memory = store.save(content="Original content", scope="project")

        updated = store.update(
            memory.id,
            "project",
            content="Updated content",
        )

        assert updated is not None
        assert updated.content == "Updated content"
        assert updated.updated_at > memory.created_at

    def test_pin_unpin_memory(self, store: MemoryStore) -> None:
        """Test pinning and unpinning a memory."""
        memory = store.save(content="Test", scope="project")
        assert memory.pinned is False

        pinned = store.pin(memory.id, "project")
        assert pinned is not None
        assert pinned.pinned is True

        unpinned = store.unpin(memory.id, "project")
        assert unpinned is not None
        assert unpinned.pinned is False

    def test_delete_memory(self, store: MemoryStore) -> None:
        """Test deleting a memory."""
        memory = store.save(content="To be deleted", scope="project")

        deleted = store.delete(memory.id, "project")
        assert deleted is True

        retrieved = store.get(memory.id, "project")
        assert retrieved is None

    def test_delete_nonexistent_memory(self, store: MemoryStore) -> None:
        """Test deleting a nonexistent memory."""
        deleted = store.delete("mem_nonexistent", "project")
        assert deleted is False

    def test_delete_matching(self, store: MemoryStore) -> None:
        """Test deleting memories matching a pattern."""
        store.save(content="Keep this", scope="project")
        store.save(content="Delete JWT related", scope="project")
        store.save(content="Also JWT token info", scope="project")

        count = store.delete_matching("JWT", "project")

        assert count == 2
        remaining = store.list("project")
        assert len(remaining) == 1
        assert remaining[0].content == "Keep this"

    def test_reset(self, store: MemoryStore) -> None:
        """Test resetting all memories."""
        store.save(content="Memory 1", scope="project")
        store.save(content="Memory 2", scope="project")
        store.save(content="Memory 3", scope="project")

        count = store.reset("project")

        assert count == 3
        assert store.count("project") == 0

    def test_count(self, store: MemoryStore) -> None:
        """Test counting memories."""
        assert store.count("project") == 0

        store.save(content="Memory 1", scope="project")
        store.save(content="Memory 2", scope="project")

        assert store.count("project") == 2

    def test_memory_to_dict(self, store: MemoryStore) -> None:
        """Test Memory.to_dict() method."""
        memory = store.save(content="Test", scope="project")

        data = memory.to_dict()

        assert data["id"] == memory.id
        assert data["content"] == "Test"
        assert "created_at" in data
        assert "updated_at" in data

    def test_context_manager(self, config: Config, temp_dir) -> None:
        """Test store as context manager."""
        project_path = temp_dir / "test-project"
        project_path.mkdir()

        with MemoryStore(config, project_path) as store:
            store.save(content="Test", scope="project")
            assert store.count("project") == 1

        # Connection should be closed after exiting context


class TestGlobalStore:
    """Tests for global scope operations."""

    def test_save_global_memory(self, global_store: MemoryStore) -> None:
        """Test saving a global memory."""
        memory = global_store.save(
            content="Global memory",
            scope="global",
        )

        assert memory.scope == "global"

    def test_list_global_memories(self, global_store: MemoryStore) -> None:
        """Test listing global memories."""
        global_store.save(content="Global 1", scope="global")
        global_store.save(content="Global 2", scope="global")

        memories = global_store.list("global")

        assert len(memories) == 2


class TestMetadata:
    """Tests for metadata support."""

    def test_save_with_metadata(self, store: MemoryStore) -> None:
        """Test saving a memory with metadata."""
        metadata = {"rationale": "Performance reasons", "status": "approved"}
        memory = store.save(
            content="Use Redis for caching",
            scope="project",
            metadata=metadata,
        )

        assert memory.metadata == metadata

    def test_metadata_persists(self, store: MemoryStore) -> None:
        """Test that metadata survives save/get round-trip."""
        metadata = {"alternatives": "Memcached, in-memory", "decided_by": "team"}
        memory = store.save(
            content="Use Redis for caching",
            scope="project",
            metadata=metadata,
        )

        retrieved = store.get(memory.id, "project")
        assert retrieved is not None
        assert retrieved.metadata == metadata

    def test_save_without_metadata(self, store: MemoryStore) -> None:
        """Test that saving without metadata gives empty dict."""
        memory = store.save(content="No metadata here", scope="project")

        assert memory.metadata == {}

        retrieved = store.get(memory.id, "project")
        assert retrieved is not None
        assert retrieved.metadata == {}

    def test_update_metadata(self, store: MemoryStore) -> None:
        """Test updating metadata on an existing memory."""
        memory = store.save(
            content="Original",
            scope="project",
            metadata={"key": "old"},
        )

        updated = store.update(
            memory.id,
            "project",
            metadata={"key": "new", "extra": "value"},
        )

        assert updated is not None
        assert updated.metadata == {"key": "new", "extra": "value"}

    def test_metadata_in_to_dict(self, store: MemoryStore) -> None:
        """Test that metadata appears in to_dict output."""
        metadata = {"rationale": "Speed", "status": "approved"}
        memory = store.save(
            content="Use Redis",
            scope="project",
            metadata=metadata,
        )

        data = memory.to_dict()
        assert data["metadata"] == metadata
