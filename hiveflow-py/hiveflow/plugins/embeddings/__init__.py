"""Embedding Provider Plugin System - Pluggable embedding backends.

Embedding providers convert text to vector representations for
semantic search, similarity comparison, and context compression.

All model references use the provider:model format:
  openai:text-embedding-3-small
  cohere:embed-english-v3.0
"""

from abc import abstractmethod
from typing import Any

from hiveflow.core.registry import BasePlugin, PluginRegistry


class EmbeddingProvider(BasePlugin):
    """Base class for embedding provider plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Provider identifier (e.g., 'openai', 'cohere')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    def max_batch_size(self) -> int:
        """Maximum number of texts per batch request."""
        return 100

    @property
    def embedding_dimension(self) -> int:
        """Dimension of output embedding vectors."""
        return 0  # Unknown until configured

    @abstractmethod
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: Texts to embed
            model: Optional model override

        Returns:
            List of embedding vectors
        """
        ...

    async def embed_single(self, text: str, model: str | None = None) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed
            model: Optional model override

        Returns:
            Embedding vector
        """
        results = await self.embed([text], model=model)
        return results[0]

    def estimate_cost(self, _num_tokens: int) -> float:
        """Estimate the cost of embedding a given number of tokens.

        Override in subclasses to provide provider-specific pricing.
        Default returns 0.0 (unknown cost).

        Args:
            num_tokens: Estimated total tokens to embed.

        Returns:
            Estimated cost in USD.
        """
        return 0.0


class EmbeddingProviderRegistry(PluginRegistry["EmbeddingProvider"]):
    """Registry for embedding provider plugins.

    Discovers providers from:
    - Python entry points under 'hiveflow.embeddings'
    - Drop-in directory
    """

    def __init__(self, drop_in_dir: str | None = "embedding_providers") -> None:
        super().__init__(
            entry_point_group="hiveflow.embeddings",
            drop_in_dir=drop_in_dir,
        )

    def resolve_model(self, model_ref: str) -> tuple[EmbeddingProvider, str]:
        """Resolve a provider:model reference.

        Args:
            model_ref: Model reference in 'provider:model' format

        Returns:
            Tuple of (provider instance, model name)
        """
        if ":" not in model_ref:
            raise ValueError(
                f"Invalid embedding model reference '{model_ref}'. "
                f"Expected format: 'provider:model'"
            )
        provider_id, model_name = model_ref.split(":", 1)
        provider = self.get_or_raise(provider_id)
        return provider, model_name


# Simple in-memory vector store for basic use cases
class SimpleVectorStore:
    """In-memory vector store using cosine similarity.

    For production use, replace with a proper vector database
    (Chroma, Pinecone, etc.).
    """

    def __init__(self) -> None:
        self._vectors: list[list[float]] = []
        self._documents: list[dict[str, Any]] = []

    def add(self, vectors: list[list[float]], documents: list[dict[str, Any]]) -> None:
        """Add vectors and associated documents.

        Args:
            vectors: Embedding vectors
            documents: Associated document metadata
        """
        if len(vectors) != len(documents):
            raise ValueError("Vectors and documents must have same length")
        self._vectors.extend(vectors)
        self._documents.extend(documents)

    def search(
        self, query_vector: list[float], top_k: int = 5
    ) -> list[tuple[dict[str, Any], float]]:
        """Search for most similar documents.

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return

        Returns:
            List of (document, similarity_score) tuples
        """
        if not self._vectors:
            return []

        similarities = [_cosine_similarity(query_vector, vec) for vec in self._vectors]

        # Get top-k indices
        indexed = sorted(enumerate(similarities), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in indexed[:top_k]:
            results.append((self._documents[idx], score))
        return results

    @property
    def size(self) -> int:
        """Number of stored vectors."""
        return len(self._vectors)

    def clear(self) -> None:
        """Remove all stored vectors and documents."""
        self._vectors.clear()
        self._documents.clear()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Cosine similarity score (-1 to 1)
    """
    dot: float = sum(x * y for x, y in zip(a, b))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
