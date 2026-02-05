"""Base embedding provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_memory.config import SemanticConfig


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: The text to embed

        Returns:
            A list of floats representing the embedding vector
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the dimension of the embedding vectors."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of the embedding provider."""
        pass


def get_embedding_provider(config: SemanticConfig) -> EmbeddingProvider | None:
    """Get the appropriate embedding provider based on config.

    Args:
        config: Semantic configuration

    Returns:
        An embedding provider instance, or None if semantic search is disabled
    """
    if not config.enabled:
        return None

    if config.provider == "vertex":
        from agent_memory.embeddings.vertex import VertexEmbeddingProvider

        return VertexEmbeddingProvider(
            project_id=config.vertex_project_id,
            location=config.vertex_location,
            model=config.vertex_model,
        )
    elif config.provider == "claude":
        from agent_memory.embeddings.claude import ClaudeEmbeddingProvider

        return ClaudeEmbeddingProvider(
            api_key_env=config.claude_api_key_env,
            model=config.claude_model,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {config.provider}")
