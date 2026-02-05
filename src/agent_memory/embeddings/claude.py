"""Claude/Anthropic embedding provider."""

from __future__ import annotations

import os

from agent_memory.embeddings.base import EmbeddingProvider


class ClaudeEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using Anthropic/Claude API.

    Note: Anthropic doesn't have a dedicated embedding API, so we use
    Voyage AI embeddings which are recommended by Anthropic.
    See: https://docs.anthropic.com/en/docs/build-with-claude/embeddings
    """

    # Voyage AI model dimensions
    MODEL_DIMENSIONS = {
        "voyage-3": 1024,
        "voyage-3-lite": 512,
        "voyage-code-3": 1024,
        "voyage-finance-2": 1024,
        "voyage-law-2": 1024,
        "voyage-multilingual-2": 1024,
        "voyage-large-2": 1536,
        "voyage-2": 1024,
    }

    def __init__(
        self,
        api_key_env: str = "VOYAGE_API_KEY",
        model: str = "voyage-3-lite",
    ):
        """Initialize Claude/Voyage embedding provider.

        Args:
            api_key_env: Environment variable containing the Voyage API key
            model: Voyage embedding model name
        """
        self.api_key_env = api_key_env
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazily initialize the Voyage AI client."""
        if self._client is None:
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise ValueError(
                    f"API key not found. Set the {self.api_key_env} environment variable."
                )

            try:
                import voyageai

                self._client = voyageai.Client(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "voyageai is required for Claude-compatible embeddings. "
                    "Install it with: pip install voyageai"
                )
        return self._client

    def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: The text to embed

        Returns:
            A list of floats representing the embedding vector
        """
        client = self._get_client()
        result = client.embed([text], model=self.model)
        return result.embeddings[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        client = self._get_client()

        # Voyage AI has a limit of 128 texts per batch
        batch_size = 128
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            result = client.embed(batch, model=self.model)
            all_embeddings.extend(result.embeddings)

        return all_embeddings

    @property
    def dimension(self) -> int:
        """Return the dimension of the embedding vectors."""
        return self.MODEL_DIMENSIONS.get(self.model, 1024)

    @property
    def name(self) -> str:
        """Return the name of the embedding provider."""
        return f"voyage:{self.model}"
