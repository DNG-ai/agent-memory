"""Memory pruning logic for cleanup operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from agent_memory.store import Memory
from agent_memory.utils import get_timestamp

if TYPE_CHECKING:
    from agent_memory.config import Config
    from agent_memory.store import MemoryStore
    from agent_memory.vector_store import VectorStore


@dataclass
class PruneCandidate:
    """A memory identified for pruning."""

    memory: Memory
    reasons: list[str]  # e.g., ["older than 90d", "never accessed"]


class PruningEngine:
    """Engine for identifying and removing old/unused memories."""

    def __init__(
        self,
        config: Config,
        store: MemoryStore,
        vector_store: VectorStore | None = None,
    ):
        """Initialize the pruning engine.

        Args:
            config: Configuration object
            store: Memory store
            vector_store: Optional vector store for cleanup
        """
        self.config = config
        self.store = store
        self.vector_store = vector_store

    def find_candidates(
        self,
        scope: str | None = None,
        older_than_days: int | None = None,
        never_accessed: bool = False,
        category: str | None = None,
        exclude_pinned: bool = True,
    ) -> list[PruneCandidate]:
        """Find memories matching prune criteria.

        Args:
            scope: Limit to specific scope ("project", "group", "global")
            older_than_days: Only memories older than N days
            never_accessed: Only memories with access_count=0
            category: Limit to specific category
            exclude_pinned: Exclude pinned memories (default True)

        Returns:
            List of PruneCandidates matching criteria
        """
        candidates: list[PruneCandidate] = []
        now = get_timestamp()

        # Determine which scopes to check
        scopes = [scope] if scope else ["project", "group", "global"]

        for check_scope in scopes:
            # Get all memories for this scope
            try:
                memories = self.store.list(
                    scope=check_scope,
                    category=category,
                    pinned_only=False,
                    limit=10000,  # Get all
                )
            except Exception:
                continue

            for memory in memories:
                # Skip pinned if requested
                if exclude_pinned and memory.pinned:
                    continue

                reasons = []

                # Check age
                if older_than_days is not None:
                    age = now - memory.created_at
                    if age >= timedelta(days=older_than_days):
                        reasons.append(f"older than {older_than_days}d")

                # Check access count
                if never_accessed and memory.access_count == 0:
                    reasons.append("never accessed")

                # Only add if at least one criterion matched
                # If both criteria specified, both must match
                if older_than_days is not None and never_accessed:
                    # Both must match
                    if len(reasons) >= 2:
                        candidates.append(PruneCandidate(memory=memory, reasons=reasons))
                elif reasons:
                    # At least one matched
                    candidates.append(PruneCandidate(memory=memory, reasons=reasons))

        return candidates

    def prune(self, candidates: list[PruneCandidate]) -> int:
        """Delete the given candidates from both SQLite and vector store.

        Args:
            candidates: List of PruneCandidates to delete

        Returns:
            Number of memories deleted
        """
        deleted = 0

        for candidate in candidates:
            memory = candidate.memory

            # Delete from SQLite
            success = self.store.delete_by_id(memory.id)

            if success:
                deleted += 1

                # Delete from vector store
                if self.vector_store:
                    try:
                        self.vector_store.delete(memory.id, memory.scope)
                    except Exception:
                        pass  # Vector delete failure is not critical

        return deleted

    def get_prune_summary(self, candidates: list[PruneCandidate]) -> dict:
        """Get a summary of what would be pruned.

        Args:
            candidates: List of PruneCandidates

        Returns:
            Dictionary with summary statistics
        """
        if not candidates:
            return {
                "total": 0,
                "by_scope": {},
                "by_category": {},
                "by_reason": {},
            }

        by_scope: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_reason: dict[str, int] = {}

        for candidate in candidates:
            memory = candidate.memory

            # Count by scope
            by_scope[memory.scope] = by_scope.get(memory.scope, 0) + 1

            # Count by category
            by_category[memory.category] = by_category.get(memory.category, 0) + 1

            # Count by reason
            for reason in candidate.reasons:
                by_reason[reason] = by_reason.get(reason, 0) + 1

        return {
            "total": len(candidates),
            "by_scope": by_scope,
            "by_category": by_category,
            "by_reason": by_reason,
        }
