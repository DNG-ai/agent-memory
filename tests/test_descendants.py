"""Tests for hierarchical descendant project lookup."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from agent_memory.config import Config, find_descendant_project_paths, load_config
from agent_memory.store import MemoryStore


@pytest.fixture
def hierarchy_config(tmp_path: Path) -> Config:
    """Create a config with a temp base path."""
    return load_config(tmp_path)


def _create_project(config: Config, project_dir: Path) -> Path:
    """Create a project storage directory with a .project_path ref file.

    Returns the storage path.
    """
    project_hash = hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:16]
    storage = config.projects_path / project_hash
    storage.mkdir(parents=True, exist_ok=True)
    (storage / ".project_path").write_text(str(project_dir.resolve()))
    (storage / "summaries").mkdir(exist_ok=True)
    return storage


def _save_memory_to_db(storage: Path, memory_id: str, content: str, **kwargs) -> None:
    """Insert a memory directly into a project's memories.db."""
    db_path = storage / "memories.db"
    conn = sqlite3.connect(str(db_path))
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
    conn.execute(
        """
        INSERT INTO memories (id, content, category, scope, project_path, pinned,
                              created_at, updated_at, source, metadata, groups)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '[]')
        """,
        (
            memory_id,
            content,
            kwargs.get("category", "factual"),
            "project",
            str(kwargs.get("project_path", "")),
            int(kwargs.get("pinned", False)),
            kwargs.get("created_at", "2025-01-15T10:00:00+00:00"),
            kwargs.get("updated_at", "2025-01-15T10:00:00+00:00"),
            kwargs.get("source", "user_explicit"),
        ),
    )
    conn.commit()
    conn.close()


class TestFindDescendantProjectPaths:
    """Tests for find_descendant_project_paths()."""

    def test_finds_child_projects(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should find projects that are children of the parent."""
        parent = tmp_path / "workspace" / "studio"
        child1 = parent / "db-writer"
        child2 = parent / "api-server"

        # Create storage entries
        _create_project(hierarchy_config, child1)
        _create_project(hierarchy_config, child2)

        results = find_descendant_project_paths(hierarchy_config, parent)

        original_paths = {orig for orig, _storage in results}
        assert child1.resolve() in original_paths
        assert child2.resolve() in original_paths

    def test_excludes_parent_itself(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should not include the parent directory itself."""
        parent = tmp_path / "workspace" / "studio"
        _create_project(hierarchy_config, parent)

        results = find_descendant_project_paths(hierarchy_config, parent)
        original_paths = {orig for orig, _storage in results}
        assert parent.resolve() not in original_paths

    def test_excludes_non_descendants(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should not include projects that aren't descendants."""
        parent = tmp_path / "workspace" / "studio"
        sibling = tmp_path / "workspace" / "other-project"

        _create_project(hierarchy_config, sibling)

        results = find_descendant_project_paths(hierarchy_config, parent)
        original_paths = {orig for orig, _storage in results}
        assert sibling.resolve() not in original_paths

    def test_shallow_path_safety_guard(self, hierarchy_config: Config) -> None:
        """Should return empty for paths with <= 2 components."""
        # "/" has 1 component
        results = find_descendant_project_paths(hierarchy_config, Path("/"))
        assert results == []

        # "/Users" has 2 components
        results = find_descendant_project_paths(hierarchy_config, Path("/Users"))
        assert results == []

    def test_max_results_cap(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should cap results at max_results."""
        parent = tmp_path / "workspace" / "studio"
        for i in range(5):
            child = parent / f"project-{i}"
            _create_project(hierarchy_config, child)

        results = find_descendant_project_paths(hierarchy_config, parent, max_results=3)
        assert len(results) <= 3

    def test_empty_projects_dir(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should return empty list when no projects exist."""
        parent = tmp_path / "workspace" / "studio"
        results = find_descendant_project_paths(hierarchy_config, parent)
        assert results == []

    def test_finds_deeply_nested(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should find deeply nested descendants."""
        parent = tmp_path / "workspace" / "studio"
        deep_child = parent / "packages" / "core" / "lib"

        _create_project(hierarchy_config, deep_child)

        results = find_descendant_project_paths(hierarchy_config, parent)
        original_paths = {orig for orig, _storage in results}
        assert deep_child.resolve() in original_paths


class TestListWithDescendants:
    """Tests for MemoryStore.list_with_descendants()."""

    def test_merges_current_and_descendant(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should include memories from both current project and descendants."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "db-writer"
        child.mkdir(parents=True, exist_ok=True)

        # Save a memory to the child project
        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_child1", "Child memory about db-writer")

        # Save a memory to the parent project
        parent_store = MemoryStore(hierarchy_config, parent)
        parent_store.save(content="Parent memory about studio", scope="project")

        # List from parent should include both
        memories = parent_store.list_with_descendants()
        contents = [m.content for m in memories]
        assert "Parent memory about studio" in contents
        assert "Child memory about db-writer" in contents
        parent_store.close()

    def test_deduplicates_by_id(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should not return duplicate memory IDs."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_dup", "Duplicate test")

        parent_store = MemoryStore(hierarchy_config, parent)
        memories = parent_store.list_with_descendants()
        ids = [m.id for m in memories]
        assert len(ids) == len(set(ids)), "Found duplicate IDs"
        parent_store.close()

    def test_filters_by_category(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should respect category filter across descendants."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_fact", "A fact", category="factual")
        _save_memory_to_db(child_storage, "mem_dec", "A decision", category="decision")

        parent_store = MemoryStore(hierarchy_config, parent)
        factual = parent_store.list_with_descendants(category="factual")
        assert all(m.category == "factual" for m in factual)
        assert any(m.id == "mem_fact" for m in factual)
        assert not any(m.id == "mem_dec" for m in factual)
        parent_store.close()

    def test_pinned_only(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should respect pinned_only filter."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_pin", "Pinned item", pinned=True)
        _save_memory_to_db(child_storage, "mem_nopin", "Not pinned")

        parent_store = MemoryStore(hierarchy_config, parent)
        pinned = parent_store.list_with_descendants(pinned_only=True)
        assert any(m.id == "mem_pin" for m in pinned)
        assert not any(m.id == "mem_nopin" for m in pinned)
        parent_store.close()

    def test_sorted_by_created_at_desc(self, hierarchy_config: Config, tmp_path: Path) -> None:
        """Should return memories sorted by created_at descending."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(
            child_storage, "mem_old", "Old memory", created_at="2024-01-01T00:00:00+00:00"
        )
        _save_memory_to_db(
            child_storage, "mem_new", "New memory", created_at="2025-06-01T00:00:00+00:00"
        )

        parent_store = MemoryStore(hierarchy_config, parent)
        memories = parent_store.list_with_descendants()
        if len(memories) >= 2:
            assert memories[0].created_at >= memories[1].created_at
        parent_store.close()


class TestSearchWithDescendants:
    """Tests for MemoryStore.search_with_descendants()."""

    def test_searches_descendant_projects(
        self, hierarchy_config: Config, tmp_path: Path
    ) -> None:
        """Should find matching memories in descendant projects."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "db-writer"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_s1", "Stripe webhook configuration")
        _save_memory_to_db(child_storage, "mem_s2", "Database migration notes")

        parent_store = MemoryStore(hierarchy_config, parent)
        results = parent_store.search_with_descendants("Stripe")
        assert any(m.id == "mem_s1" for m in results)
        assert not any(m.id == "mem_s2" for m in results)
        parent_store.close()

    def test_includes_current_project_results(
        self, hierarchy_config: Config, tmp_path: Path
    ) -> None:
        """Should include results from the current project too."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)

        parent_store = MemoryStore(hierarchy_config, parent)
        parent_store.save(content="Parent has API docs", scope="project")

        results = parent_store.search_with_descendants("API")
        assert any("API" in m.content for m in results)
        parent_store.close()

    def test_deduplicates_search_results(
        self, hierarchy_config: Config, tmp_path: Path
    ) -> None:
        """Search results should be deduplicated by ID."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_unique", "Unique search term xyz123")

        parent_store = MemoryStore(hierarchy_config, parent)
        results = parent_store.search_with_descendants("xyz123")
        ids = [m.id for m in results]
        assert len(ids) == len(set(ids))
        parent_store.close()


class TestSaveTargetsExactDirectory:
    """Tests that save always targets the exact current directory."""

    def test_save_goes_to_current_project_only(
        self, hierarchy_config: Config, tmp_path: Path
    ) -> None:
        """Save should only write to the current project's DB, not descendants."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        _create_project(hierarchy_config, child)

        parent_store = MemoryStore(hierarchy_config, parent)
        parent_store.save(content="Saved from parent", scope="project")

        # Check that child project has no memories
        child_store = MemoryStore(hierarchy_config, child)
        child_memories = child_store.list(scope="project")
        assert not any(m.content == "Saved from parent" for m in child_memories)

        # Check that parent has the memory
        parent_memories = parent_store.list(scope="project")
        assert any(m.content == "Saved from parent" for m in parent_memories)

        parent_store.close()
        child_store.close()


class TestExactFlagBehavior:
    """Tests for --exact flag behavior (via store methods)."""

    def test_list_exact_excludes_descendants(
        self, hierarchy_config: Config, tmp_path: Path
    ) -> None:
        """list(scope='project') should not include descendant memories."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_child_only", "Child-only memory")

        parent_store = MemoryStore(hierarchy_config, parent)

        # Exact (plain list) should NOT include child
        exact_memories = parent_store.list(scope="project")
        assert not any(m.id == "mem_child_only" for m in exact_memories)

        # With descendants SHOULD include child
        desc_memories = parent_store.list_with_descendants()
        assert any(m.id == "mem_child_only" for m in desc_memories)
        parent_store.close()

    def test_search_exact_excludes_descendants(
        self, hierarchy_config: Config, tmp_path: Path
    ) -> None:
        """search_keyword should not include descendant memories."""
        parent = tmp_path / "workspace" / "studio"
        parent.mkdir(parents=True, exist_ok=True)
        child = parent / "sub"
        child.mkdir(parents=True, exist_ok=True)

        child_storage = _create_project(hierarchy_config, child)
        _save_memory_to_db(child_storage, "mem_child_s", "UniqueSearchTerm42")

        parent_store = MemoryStore(hierarchy_config, parent)

        # Exact search should NOT include child
        exact_results = parent_store.search_keyword("UniqueSearchTerm42", "project")
        assert not any(m.id == "mem_child_s" for m in exact_results)

        # Descendant search SHOULD include child
        desc_results = parent_store.search_with_descendants("UniqueSearchTerm42")
        assert any(m.id == "mem_child_s" for m in desc_results)
        parent_store.close()
