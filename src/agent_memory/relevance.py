"""Relevance scoring and retrieval logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from agent_memory.config import Config
from agent_memory.store import Memory, MemoryStore
from agent_memory.utils import get_timestamp

if TYPE_CHECKING:
    from agent_memory.vector_store import VectorSearchResult, VectorStore


@dataclass
class StartupContext:
    """Context loaded at session start."""

    pinned_memories: list[Memory]
    has_previous_session: bool
    previous_session_id: str | None
    previous_session_summaries: list[Memory]

    def to_dict(self) -> dict:
        """Convert to dictionary for display."""
        return {
            "pinned_count": len(self.pinned_memories),
            "has_previous_session": self.has_previous_session,
            "previous_session_id": self.previous_session_id,
            "summary_count": len(self.previous_session_summaries),
        }


@dataclass
class RelevantMemories:
    """Collection of relevant memories."""

    semantic_results: list[VectorSearchResult]
    keyword_results: list[Memory]
    pinned: list[Memory]

    @property
    def all_memory_ids(self) -> set[str]:
        """Get all unique memory IDs."""
        ids = {r.memory_id for r in self.semantic_results}
        ids.update(m.id for m in self.keyword_results)
        ids.update(m.id for m in self.pinned)
        return ids


class RelevanceEngine:
    """Engine for determining relevant memories."""

    def __init__(
        self,
        config: Config,
        store: MemoryStore,
        vector_store: VectorStore | None = None,
    ):
        """Initialize the relevance engine.

        Args:
            config: Configuration object
            store: Memory store for metadata
            vector_store: Optional vector store for semantic search
        """
        self.config = config
        self.store = store
        self.vector_store = vector_store

    def get_startup_context(self, project_path: Path) -> StartupContext:
        """Get context to load at session start.

        This includes:
        - All pinned memories (always loaded)
        - Previous session info (for user prompt)

        Args:
            project_path: The project path

        Returns:
            StartupContext with memories to load
        """
        pinned_memories = []

        # Get pinned project memories
        try:
            pinned_memories.extend(self.store.list_pinned("project"))
        except Exception:
            pass

        # Get pinned global memories
        try:
            pinned_memories.extend(self.store.list_pinned("global"))
        except Exception:
            pass

        # Check for previous session
        previous_session_id = None
        previous_session_summaries: list[Memory] = []
        has_previous_session = False

        try:
            # Get recent session summaries (from last 7 days)
            now = get_timestamp()
            recent_cutoff = now - timedelta(days=7)

            summaries = self.store.list(
                scope="project",
                category="session_summary",
                limit=10,
            )

            if summaries:
                has_previous_session = True
                # Group by session (assuming metadata contains session_id)
                latest_session_id = None
                for summary in summaries:
                    if summary.created_at >= recent_cutoff:
                        session_id = summary.metadata.get("session_id")
                        if session_id and latest_session_id is None:
                            latest_session_id = session_id
                        if session_id == latest_session_id:
                            previous_session_summaries.append(summary)

                previous_session_id = latest_session_id

        except Exception:
            pass

        return StartupContext(
            pinned_memories=pinned_memories,
            has_previous_session=has_previous_session,
            previous_session_id=previous_session_id,
            previous_session_summaries=previous_session_summaries,
        )

    def get_relevant_memories(
        self,
        query: str,
        current_files: list[str] | None = None,
        limit: int | None = None,
        threshold: float | None = None,
        include_pinned: bool = True,
    ) -> RelevantMemories:
        """Get memories relevant to a query.

        Args:
            query: The search query
            current_files: Optional list of current file paths for context
            limit: Maximum results (uses config default if not provided)
            threshold: Similarity threshold (uses config default if not provided)
            include_pinned: Whether to include pinned memories

        Returns:
            RelevantMemories with results from different sources
        """
        if limit is None:
            limit = self.config.relevance.search_limit

        if threshold is None:
            threshold = self.config.semantic.threshold

        # Build search context
        search_context = query
        if current_files:
            # Add file context (just names, not full content)
            file_names = " ".join(Path(f).name for f in current_files[:5])
            search_context = f"{query} {file_names}"

        # Semantic search
        semantic_results: list[VectorSearchResult] = []
        if self.vector_store and self.vector_store.is_enabled():
            semantic_results = self.vector_store.search_combined(
                search_context,
                limit=limit,
                threshold=threshold,
            )

        # Keyword fallback/supplement
        keyword_results: list[Memory] = []
        if not semantic_results or len(semantic_results) < limit:
            # Try keyword search
            remaining = limit - len(semantic_results)
            try:
                keyword_results = self.store.search_keyword(query, "project", remaining)
                # Exclude memories already in semantic results
                semantic_ids = {r.memory_id for r in semantic_results}
                keyword_results = [m for m in keyword_results if m.id not in semantic_ids]
            except Exception:
                pass

            # Also search global if configured
            if self.config.relevance.include_global and len(keyword_results) < remaining:
                try:
                    global_results = self.store.search_keyword(
                        query, "global", remaining - len(keyword_results)
                    )
                    semantic_ids = {r.memory_id for r in semantic_results}
                    keyword_ids = {m.id for m in keyword_results}
                    global_results = [
                        m
                        for m in global_results
                        if m.id not in semantic_ids and m.id not in keyword_ids
                    ]
                    keyword_results.extend(global_results)
                except Exception:
                    pass

        # Get pinned memories
        pinned: list[Memory] = []
        if include_pinned:
            try:
                pinned = self.store.list_pinned("project")
                pinned.extend(self.store.list_pinned("global"))
            except Exception:
                pass

        return RelevantMemories(
            semantic_results=semantic_results,
            keyword_results=keyword_results,
            pinned=pinned,
        )

    def get_recent_decisions(
        self,
        days: int = 30,
        limit: int = 5,
    ) -> list[Memory]:
        """Get recent decision memories.

        Args:
            days: Number of days to look back
            limit: Maximum number of results

        Returns:
            List of decision memories
        """
        now = get_timestamp()
        cutoff = now - timedelta(days=days)

        decisions = self.store.list(
            scope="project",
            category="decision",
            limit=limit * 2,  # Get extra for filtering
        )

        # Filter by date
        recent_decisions = [d for d in decisions if d.created_at >= cutoff]

        return recent_decisions[:limit]

    def get_recent_facts(
        self,
        limit: int = 5,
    ) -> list[Memory]:
        """Get recent factual memories.

        Args:
            limit: Maximum number of results

        Returns:
            List of factual memories
        """
        return self.store.list(
            scope="project",
            category="factual",
            limit=limit,
        )

    def score_memory_relevance(
        self,
        memory: Memory,
        query: str | None = None,
        semantic_score: float | None = None,
    ) -> float:
        """Calculate a relevance score for a memory.

        Args:
            memory: The memory to score
            query: Optional query for keyword matching
            semantic_score: Optional pre-computed semantic similarity

        Returns:
            Relevance score between 0 and 1
        """
        score = 0.0

        # Base score from semantic similarity
        if semantic_score is not None:
            score = semantic_score * 0.6

        # Boost for pinned memories
        if memory.pinned:
            score += 0.3

        # Boost for decisions (more actionable)
        if memory.category == "decision":
            score += 0.1

        # Recency boost (memories from last 7 days)
        now = get_timestamp()
        age_days = (now - memory.created_at).days
        if age_days <= 7:
            score += 0.1 * (1 - age_days / 7)

        # Keyword match boost
        if query:
            query_lower = query.lower()
            content_lower = memory.content.lower()
            if query_lower in content_lower:
                score += 0.2

        return min(score, 1.0)
