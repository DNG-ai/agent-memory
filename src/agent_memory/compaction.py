"""Memory compaction using DBSCAN clustering and LLM summarization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np

from agent_memory.llm import LLMProvider
from agent_memory.store import Memory
from agent_memory.utils import get_timestamp

if TYPE_CHECKING:
    from agent_memory.config import Config
    from agent_memory.store import MemoryStore
    from agent_memory.vector_store import VectorStore


@dataclass
class MemoryCluster:
    """A cluster of similar memories to be compacted."""

    memories: list[Memory] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        """Get memory IDs in this cluster."""
        return [m.id for m in self.memories]

    @property
    def contents(self) -> list[str]:
        """Get memory contents, ordered by creation time (oldest first)."""
        sorted_memories = sorted(self.memories, key=lambda m: m.created_at)
        return [m.content for m in sorted_memories]

    @property
    def size(self) -> int:
        """Number of memories in this cluster."""
        return len(self.memories)


class CompactionEngine:
    """Engine for clustering and compacting similar memories."""

    def __init__(
        self,
        config: Config,
        store: MemoryStore,
        vector_store: VectorStore | None = None,
    ):
        """Initialize the compaction engine.

        Args:
            config: Configuration object
            store: Memory store
            vector_store: Vector store for embeddings
        """
        self.config = config
        self.store = store
        self.vector_store = vector_store
        self.llm = LLMProvider(config)

    def find_clusters(
        self,
        scope: str | None = None,
        category: str | None = None,
        older_than_days: int | None = None,
        similarity_threshold: float = 0.8,
        min_cluster_size: int = 3,
    ) -> list[MemoryCluster]:
        """Find clusters of similar memories using DBSCAN.

        Args:
            scope: Limit to specific scope
            category: Limit to specific category
            older_than_days: Only include memories older than N days
            similarity_threshold: Similarity threshold for clustering (0.0-1.0)
            min_cluster_size: Minimum memories per cluster

        Returns:
            List of MemoryClusters
        """
        if not self.vector_store or not self.vector_store.embedding_provider:
            raise ValueError("Vector store with embeddings required for clustering")

        # Get memories matching criteria
        memories = self._get_candidate_memories(scope, category, older_than_days)

        if len(memories) < min_cluster_size:
            return []

        # Get embeddings for all memories
        embeddings = self._get_embeddings(memories)

        if not embeddings:
            return []

        # Run DBSCAN clustering
        clusters = self._cluster_dbscan(
            memories,
            embeddings,
            similarity_threshold,
            min_cluster_size,
        )

        return clusters

    def _get_candidate_memories(
        self,
        scope: str | None,
        category: str | None,
        older_than_days: int | None,
    ) -> list[Memory]:
        """Get memories matching the filter criteria."""
        memories: list[Memory] = []
        now = get_timestamp()

        scopes = [scope] if scope else ["project", "group", "global"]

        for check_scope in scopes:
            try:
                scope_memories = self.store.list(
                    scope=check_scope,
                    category=category,
                    pinned_only=False,
                    limit=10000,
                )

                # Filter by age if specified
                if older_than_days is not None:
                    cutoff = now - timedelta(days=older_than_days)
                    scope_memories = [m for m in scope_memories if m.created_at < cutoff]

                memories.extend(scope_memories)
            except Exception:
                continue

        return memories

    def _get_embeddings(self, memories: list[Memory]) -> list[list[float]]:
        """Get embeddings for memories."""
        if not self.vector_store or not self.vector_store.embedding_provider:
            return []

        provider = self.vector_store.embedding_provider
        contents = [m.content for m in memories]

        try:
            embeddings = provider.embed_batch(contents)
            return embeddings
        except Exception:
            return []

    def _cluster_dbscan(
        self,
        memories: list[Memory],
        embeddings: list[list[float]],
        similarity_threshold: float,
        min_cluster_size: int,
    ) -> list[MemoryCluster]:
        """Run DBSCAN clustering on embeddings.

        Args:
            memories: List of memories
            embeddings: Corresponding embeddings
            similarity_threshold: Similarity threshold (converted to distance)
            min_cluster_size: Minimum cluster size

        Returns:
            List of MemoryClusters
        """
        from sklearn.cluster import DBSCAN
        from sklearn.metrics.pairwise import cosine_distances

        # Convert embeddings to numpy array
        X = np.array(embeddings)

        # Compute cosine distance matrix
        # Similarity threshold 0.8 means distance threshold 0.2
        eps = 1.0 - similarity_threshold

        # Run DBSCAN
        # Using precomputed distances for cosine similarity
        distance_matrix = cosine_distances(X)
        clustering = DBSCAN(
            eps=eps,
            min_samples=min_cluster_size,
            metric="precomputed",
        ).fit(distance_matrix)

        # Group memories by cluster label
        labels = clustering.labels_
        cluster_dict: dict[int, MemoryCluster] = {}

        for i, label in enumerate(labels):
            if label == -1:  # Noise point
                continue

            if label not in cluster_dict:
                cluster_dict[label] = MemoryCluster()

            cluster_dict[label].memories.append(memories[i])
            cluster_dict[label].embeddings.append(embeddings[i])

        # Filter clusters by minimum size (DBSCAN should already do this, but double-check)
        clusters = [c for c in cluster_dict.values() if c.size >= min_cluster_size]

        return clusters

    def generate_summary(self, cluster: MemoryCluster) -> str:
        """Generate LLM summary for a cluster.

        Args:
            cluster: The cluster to summarize

        Returns:
            Summary string

        Raises:
            Exception: If LLM call fails (caller should abort)
        """
        contents = cluster.contents  # Already sorted oldest to newest
        return self.llm.summarize(contents)

    def compact_cluster(
        self,
        cluster: MemoryCluster,
        summary: str,
        target_scope: str,
        target_groups: list[str] | None = None,
    ) -> Memory:
        """Replace a cluster with a single compacted memory.

        Args:
            cluster: The cluster to compact
            summary: The generated summary
            target_scope: Scope for the new memory
            target_groups: Groups for group-scoped memories

        Returns:
            The newly created compacted memory

        Raises:
            Exception: If any operation fails
        """
        # Determine category (use most common from cluster, or "factual")
        categories = [m.category for m in cluster.memories]
        category = max(set(categories), key=categories.count)

        # Create metadata for the new memory
        metadata = {
            "compacted_from": cluster.ids,
            "compacted_at": get_timestamp().isoformat(),
            "original_count": cluster.size,
        }

        # Save new compacted memory
        new_memory = self.store.save(
            content=summary,
            category=category,
            scope=target_scope,
            pinned=False,
            source="auto_compaction",
            metadata=metadata,
            groups=target_groups if target_scope == "group" else None,
        )

        # Add to vector store
        if self.vector_store:
            try:
                self.vector_store.add(
                    memory_id=new_memory.id,
                    content=summary,
                    category=category,
                    scope=target_scope,
                    groups=target_groups if target_scope == "group" else None,
                )
            except Exception:
                pass  # Vector add failure is not critical

        # Delete original memories
        for memory in cluster.memories:
            self.store.delete_by_id(memory.id)
            if self.vector_store:
                try:
                    self.vector_store.delete(memory.id, memory.scope)
                except Exception:
                    pass

        return new_memory

    def get_cluster_summary(self, clusters: list[MemoryCluster]) -> dict:
        """Get a summary of clusters found.

        Args:
            clusters: List of MemoryClusters

        Returns:
            Dictionary with summary statistics
        """
        if not clusters:
            return {
                "cluster_count": 0,
                "total_memories": 0,
                "avg_cluster_size": 0,
                "clusters": [],
            }

        total_memories = sum(c.size for c in clusters)
        avg_size = total_memories / len(clusters)

        cluster_info = []
        for i, cluster in enumerate(clusters):
            cluster_info.append(
                {
                    "index": i,
                    "size": cluster.size,
                    "memory_ids": cluster.ids,
                    "previews": [
                        {
                            "id": m.id,
                            "content": m.content[:80] + "..." if len(m.content) > 80 else m.content,
                        }
                        for m in cluster.memories
                    ],
                }
            )

        return {
            "cluster_count": len(clusters),
            "total_memories": total_memories,
            "avg_cluster_size": round(avg_size, 1),
            "clusters": cluster_info,
        }
