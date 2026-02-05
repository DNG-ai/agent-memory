"""Embedding providers for semantic search."""

from agent_memory.embeddings.base import EmbeddingProvider
from agent_memory.embeddings.vertex import VertexEmbeddingProvider
from agent_memory.embeddings.claude import ClaudeEmbeddingProvider

__all__ = ["EmbeddingProvider", "VertexEmbeddingProvider", "ClaudeEmbeddingProvider"]
