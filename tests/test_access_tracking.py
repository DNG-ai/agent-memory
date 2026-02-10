"""Tests for access tracking in the memory store."""

from __future__ import annotations

from agent_memory.store import MemoryStore


class TestAccessTracking:
    """Tests for access tracking via record_access and record_access_batch."""

    def test_record_access_increments_count(self, store: MemoryStore) -> None:
        """Test that record_access increments access_count."""
        memory = store.save(content="Test content", scope="project")
        assert memory.access_count == 0

        store.record_access(memory.id, "project")
        updated = store.get(memory.id, "project")
        assert updated is not None
        assert updated.access_count == 1
        assert updated.last_accessed_at is not None

    def test_record_access_multiple_times(self, store: MemoryStore) -> None:
        """Test multiple access recordings."""
        memory = store.save(content="Frequently accessed", scope="project")

        store.record_access(memory.id, "project")
        store.record_access(memory.id, "project")
        store.record_access(memory.id, "project")

        updated = store.get(memory.id, "project")
        assert updated is not None
        assert updated.access_count == 3

    def test_record_access_batch(self, store: MemoryStore) -> None:
        """Test batch access recording."""
        m1 = store.save(content="Memory 1", scope="project")
        m2 = store.save(content="Memory 2", scope="project")
        m3 = store.save(content="Memory 3", scope="project")

        store.record_access_batch([m1.id, m2.id, m3.id], "project")

        for mid in [m1.id, m2.id, m3.id]:
            updated = store.get(mid, "project")
            assert updated is not None
            assert updated.access_count == 1

    def test_record_access_batch_empty(self, store: MemoryStore) -> None:
        """Test batch access recording with empty list."""
        # Should not raise
        store.record_access_batch([], "project")

    def test_get_most_accessed(self, store: MemoryStore) -> None:
        """Test retrieving most accessed memories."""
        m1 = store.save(content="Popular memory", scope="project")
        m2 = store.save(content="Less popular", scope="project")
        m3 = store.save(content="Never accessed", scope="project")

        # Access m1 three times, m2 once
        for _ in range(3):
            store.record_access(m1.id, "project")
        store.record_access(m2.id, "project")

        most_accessed = store.get_most_accessed("project", limit=5)
        assert len(most_accessed) == 2
        assert most_accessed[0].id == m1.id
        assert most_accessed[0].access_count == 3
        assert most_accessed[1].id == m2.id
        assert most_accessed[1].access_count == 1

    def test_get_pin_candidates(self, store: MemoryStore) -> None:
        """Test retrieving pin candidates (high access, not pinned)."""
        m1 = store.save(content="Should be pinned", scope="project")
        m2 = store.save(content="Already pinned", scope="project", pinned=True)
        m3 = store.save(content="Low access", scope="project")

        # m1 gets 5 accesses
        for _ in range(5):
            store.record_access(m1.id, "project")
        # m2 gets 5 accesses but is already pinned
        for _ in range(5):
            store.record_access(m2.id, "project")
        # m3 gets 1 access (below threshold)
        store.record_access(m3.id, "project")

        candidates = store.get_pin_candidates("project", min_access=3, limit=5)
        assert len(candidates) == 1
        assert candidates[0].id == m1.id
        assert candidates[0].access_count == 5

    def test_record_access_for_memories_helper(self, store: MemoryStore) -> None:
        """Test the _record_access_for_memories helper function."""
        from agent_memory.cli import _record_access_for_memories

        m1 = store.save(content="Memory A", scope="project")
        m2 = store.save(content="Memory B", scope="project")

        _record_access_for_memories(store, [m1, m2])

        updated1 = store.get(m1.id, "project")
        updated2 = store.get(m2.id, "project")
        assert updated1 is not None and updated1.access_count == 1
        assert updated2 is not None and updated2.access_count == 1

    def test_record_access_for_memories_mixed_scopes(
        self, store: MemoryStore
    ) -> None:
        """Test helper with memories from different scopes."""
        from agent_memory.cli import _record_access_for_memories

        m_project = store.save(content="Project memory", scope="project")
        m_global = store.save(content="Global memory", scope="global")

        _record_access_for_memories(store, [m_project, m_global])

        up_project = store.get(m_project.id, "project")
        up_global = store.get(m_global.id, "global")
        assert up_project is not None and up_project.access_count == 1
        assert up_global is not None and up_global.access_count == 1

    def test_record_access_for_memories_never_raises(
        self, store: MemoryStore
    ) -> None:
        """Test that helper never raises even with bad data."""
        from agent_memory.cli import _record_access_for_memories

        # Should not raise with empty list
        _record_access_for_memories(store, [])
