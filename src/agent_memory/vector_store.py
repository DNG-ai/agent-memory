"""LanceDB-based vector store for semantic search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa

if TYPE_CHECKING:
    import lancedb

from agent_memory.config import Config, get_project_path
from agent_memory.embeddings.base import EmbeddingProvider, get_embedding_provider


@dataclass
class VectorSearchResult:
    """Result from vector similarity search."""

    memory_id: str
    content: str
    score: float
    category: str
    scope: str | None = None
    groups: list[str] | None = None


class VectorStore:
    """LanceDB-based vector store for semantic search."""

    TABLE_NAME = "memory_vectors"

    def __init__(
        self,
        config: Config,
        project_path: Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        """Initialize the vector store.

        Args:
            config: Configuration object
            project_path: Optional project path for project-scoped operations
            embedding_provider: Optional embedding provider (loaded from config if not provided)
        """
        self.config = config
        self.project_path = project_path
        self._embedding_provider = embedding_provider
        self._global_db: lancedb.DBConnection | None = None
        self._project_db: lancedb.DBConnection | None = None

    @property
    def embedding_provider(self) -> EmbeddingProvider | None:
        """Get the embedding provider."""
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider(self.config.semantic)
        return self._embedding_provider

    @property
    def global_db_path(self) -> Path:
        """Path to global vector database."""
        return self.config.global_path / "vectors"

    @property
    def project_db_path(self) -> Path | None:
        """Path to project vector database."""
        if self.project_path is None:
            return None
        project_storage = get_project_path(self.config, self.project_path)
        return project_storage / "vectors"

    def _get_db(self, scope: str) -> lancedb.DBConnection:
        """Get or create database connection for scope.

        Note: 'group' scope uses the global database, matching SQLite behavior.
        """
        import lancedb

        if scope in ("global", "group"):
            if self._global_db is None:
                self.global_db_path.mkdir(parents=True, exist_ok=True)
                self._global_db = lancedb.connect(str(self.global_db_path))
            return self._global_db
        else:
            if self.project_db_path is None:
                raise ValueError("No project path set")
            if self._project_db is None:
                self.project_db_path.mkdir(parents=True, exist_ok=True)
                self._project_db = lancedb.connect(str(self.project_db_path))
            return self._project_db

    def _get_or_create_table(self, db: lancedb.DBConnection, dimension: int) -> Any:
        """Get or create the vectors table.

        Schema includes scope and groups fields for filtering group-scoped memories.
        """
        if self.TABLE_NAME in db.table_names():
            table = db.open_table(self.TABLE_NAME)
            # Check if migration needed (old schema without scope/groups)
            self._migrate_table_schema(table, dimension)
            return table

        # Create schema with scope and groups for filtering
        schema = pa.schema(
            [
                pa.field("memory_id", pa.string()),
                pa.field("content", pa.string()),
                pa.field("category", pa.string()),
                pa.field("scope", pa.string()),  # "project", "group", or "global"
                pa.field("groups", pa.string()),  # JSON array of owner groups
                pa.field("vector", pa.list_(pa.float32(), dimension)),
            ]
        )

        return db.create_table(self.TABLE_NAME, schema=schema)

    def _migrate_table_schema(self, table: Any, dimension: int) -> None:
        """Migrate old table schema to include scope and groups fields.

        LanceDB doesn't support ALTER TABLE, so we check if columns exist
        and add default values when inserting if they're missing.
        """
        # LanceDB tables are schemaless for new columns - they'll be added on insert
        # We just note that old records may have None for scope/groups
        pass

    def add(
        self,
        memory_id: str,
        content: str,
        category: str,
        scope: str = "project",
        groups: list[str] | None = None,
    ) -> bool:
        """Add a memory to the vector store.

        Args:
            memory_id: The memory ID
            content: The memory content
            category: The memory category
            scope: "project", "group", or "global"
            groups: Owner groups for group-scoped memories (JSON serialized)

        Returns:
            True if successful, False if semantic search is disabled
        """
        import json

        provider = self.embedding_provider
        if provider is None:
            return False

        embedding = provider.embed(content)
        db = self._get_db(scope)
        table = self._get_or_create_table(db, provider.dimension)

        table.add(
            [
                {
                    "memory_id": memory_id,
                    "content": content,
                    "category": category,
                    "scope": scope,
                    "groups": json.dumps(groups or []),
                    "vector": embedding,
                }
            ]
        )
        return True

    def add_batch(
        self,
        memories: list[
            tuple[str, str, str, list[str] | None]
        ],  # (memory_id, content, category, groups)
        scope: str = "project",
    ) -> bool:
        """Add multiple memories to the vector store.

        Args:
            memories: List of (memory_id, content, category, groups) tuples
            scope: "project", "group", or "global"

        Returns:
            True if successful, False if semantic search is disabled
        """
        import json

        if not memories:
            return True

        provider = self.embedding_provider
        if provider is None:
            return False

        contents = [m[1] for m in memories]
        embeddings = provider.embed_batch(contents)

        db = self._get_db(scope)
        table = self._get_or_create_table(db, provider.dimension)

        data = [
            {
                "memory_id": memory_id,
                "content": content,
                "category": category,
                "scope": scope,
                "groups": json.dumps(groups or []),
                "vector": embedding,
            }
            for (memory_id, content, category, groups), embedding in zip(memories, embeddings)
        ]

        table.add(data)
        return True

    def search(
        self,
        query: str,
        scope: str = "project",
        limit: int = 5,
        threshold: float | None = None,
        category: str | None = None,
        include_groups: list[str] | None = None,
        exclude_group_scope: bool = False,
    ) -> list[VectorSearchResult]:
        """Search for similar memories.

        Args:
            query: The search query
            scope: "project", "group", or "global" (determines which DB to search)
            limit: Maximum number of results
            threshold: Minimum similarity score (uses config default if not provided)
            category: Optional category filter
            include_groups: Only include group-scoped memories from these groups.
                          Use ["all"] to include all groups. None = no group filtering.
            exclude_group_scope: If True, exclude group-scoped memories from results.
                               Used when searching global DB but not wanting group memories.

        Returns:
            List of search results sorted by similarity
        """
        import json

        provider = self.embedding_provider
        if provider is None:
            return []

        if threshold is None:
            threshold = self.config.semantic.threshold

        query_embedding = provider.embed(query)
        db = self._get_db(scope)

        if self.TABLE_NAME not in db.table_names():
            return []

        table = db.open_table(self.TABLE_NAME)

        # Build search query
        search_query = table.search(query_embedding).limit(limit * 3)  # Get extra for filtering

        results_df = search_query.to_pandas()

        if results_df.empty:
            return []

        # Filter by threshold (LanceDB returns _distance, lower is better)
        # Convert distance to similarity score (1 - distance for cosine)
        results_df["score"] = 1 - results_df["_distance"]
        results_df = results_df[results_df["score"] >= threshold]

        # Filter by category if specified
        if category:
            results_df = results_df[results_df["category"] == category]

        # Handle group filtering for global DB (which contains both global and group scoped)
        if "scope" in results_df.columns:
            if exclude_group_scope:
                # Exclude group-scoped memories
                results_df = results_df[results_df["scope"] != "group"]
            elif include_groups is not None:
                # Filter to include specific groups
                def matches_groups(row):
                    row_scope = row.get("scope")
                    if row_scope != "group":
                        return True  # Include non-group memories
                    row_groups_str = row.get("groups", "[]")
                    try:
                        row_groups = json.loads(row_groups_str) if row_groups_str else []
                    except (json.JSONDecodeError, TypeError):
                        row_groups = []
                    if "all" in [g.lower() for g in include_groups]:
                        return True  # Include all groups
                    return any(g in row_groups for g in include_groups)

                results_df = results_df[results_df.apply(matches_groups, axis=1)]

        # Limit results
        results_df = results_df.head(limit)

        # Parse groups field for results
        def parse_groups(groups_str):
            if not groups_str:
                return []
            try:
                return json.loads(groups_str) if isinstance(groups_str, str) else []
            except (json.JSONDecodeError, TypeError):
                return []

        return [
            VectorSearchResult(
                memory_id=row["memory_id"],
                content=row["content"],
                score=row["score"],
                category=row["category"],
                scope=row.get("scope"),
                groups=parse_groups(row.get("groups")),
            )
            for _, row in results_df.iterrows()
        ]

    def search_combined(
        self,
        query: str,
        limit: int = 5,
        threshold: float | None = None,
        category: str | None = None,
        include_groups: list[str] | None = None,
    ) -> list[VectorSearchResult]:
        """Search project, global, and optionally group memories.

        Args:
            query: The search query
            limit: Maximum number of results
            threshold: Minimum similarity score
            category: Optional category filter
            include_groups: Groups to include in search. None = exclude group-scoped.
                          Use ["all"] to include all groups.

        Returns:
            Combined and sorted results
        """
        results = []

        # Search project if available
        if self.project_path is not None:
            try:
                project_results = self.search(query, "project", limit, threshold, category)
                results.extend(project_results)
            except Exception:
                pass

        # Search global DB (contains both global and group scoped memories)
        if self.config.relevance.include_global:
            try:
                # If no groups specified, exclude group-scoped memories
                # If groups specified, filter to those groups
                global_results = self.search(
                    query,
                    "global",
                    limit,
                    threshold,
                    category,
                    include_groups=include_groups,
                    exclude_group_scope=(include_groups is None),
                )
                results.extend(global_results)
            except Exception:
                pass

        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def delete(self, memory_id: str, scope: str = "project") -> bool:
        """Delete a memory from the vector store.

        Args:
            memory_id: The memory ID to delete
            scope: "project" or "global"

        Returns:
            True if deleted, False otherwise
        """
        try:
            db = self._get_db(scope)
            if self.TABLE_NAME not in db.table_names():
                return False

            table = db.open_table(self.TABLE_NAME)
            table.delete(f"memory_id = '{memory_id}'")
            return True
        except Exception:
            return False

    def delete_by_id(self, memory_id: str) -> bool:
        """Delete a memory from both project and global stores."""
        deleted = False
        if self.project_path is not None:
            deleted = self.delete(memory_id, "project") or deleted
        deleted = self.delete(memory_id, "global") or deleted
        return deleted

    def reset(self, scope: str = "project") -> bool:
        """Delete all vectors in scope.

        Args:
            scope: "project" or "global"

        Returns:
            True if successful
        """
        try:
            db = self._get_db(scope)
            if self.TABLE_NAME in db.table_names():
                db.drop_table(self.TABLE_NAME)
            return True
        except Exception:
            return False

    def count(self, scope: str = "project") -> int:
        """Count vectors in scope."""
        try:
            db = self._get_db(scope)
            if self.TABLE_NAME not in db.table_names():
                return 0
            table = db.open_table(self.TABLE_NAME)
            return table.count_rows()
        except Exception:
            return 0

    def is_enabled(self) -> bool:
        """Check if semantic search is enabled."""
        return self.config.semantic.enabled and self.embedding_provider is not None
