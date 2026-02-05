"""Vertex AI embedding provider."""

from __future__ import annotations

from agent_memory.embeddings.base import EmbeddingProvider


class VertexEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using Google Vertex AI."""

    # Embedding dimensions for different models
    MODEL_DIMENSIONS = {
        "text-embedding-004": 768,
        "text-embedding-005": 768,
        "textembedding-gecko@003": 768,
        "textembedding-gecko@002": 768,
        "textembedding-gecko@001": 768,
        "textembedding-gecko-multilingual@001": 768,
    }

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        model: str = "text-embedding-004",
    ):
        """Initialize Vertex AI embedding provider.

        Args:
            project_id: Google Cloud project ID
            location: Vertex AI location
            model: Embedding model name
        """
        self.project_id = project_id
        self.location = location
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazily initialize the Vertex AI client."""
        if self._client is None:
            try:
                from google.cloud import aiplatform
                from vertexai.language_models import TextEmbeddingModel

                aiplatform.init(project=self.project_id, location=self.location)
                self._client = TextEmbeddingModel.from_pretrained(self.model)
            except ImportError:
                raise ImportError(
                    "google-cloud-aiplatform is required for Vertex AI embeddings. "
                    "Install it with: pip install google-cloud-aiplatform"
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
        embeddings = client.get_embeddings([text])
        return embeddings[0].values

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

        # Vertex AI has a limit of 250 texts per batch
        batch_size = 250
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = client.get_embeddings(batch)
            all_embeddings.extend([e.values for e in embeddings])

        return all_embeddings

    @property
    def dimension(self) -> int:
        """Return the dimension of the embedding vectors."""
        return self.MODEL_DIMENSIONS.get(self.model, 768)

    @property
    def name(self) -> str:
        """Return the name of the embedding provider."""
        return f"vertex:{self.model}"
