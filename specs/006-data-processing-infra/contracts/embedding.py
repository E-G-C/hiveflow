"""Embedding Provider Interface Contract.

Defines the public contract for embedding providers. Implementations
must inherit from EmbeddingProvider and register via the
hiveflow.embeddings entry point group.

NOTE: The base class already exists in hiveflow/plugins/embeddings/__init__.py.
Changes marked with # EXISTING or # NEW.
"""


# --- Plugin Interface ---

class EmbeddingProvider:                               # EXISTING
    """Base class for embedding provider plugins.

    Properties:
        plugin_id: Unique identifier (e.g., "openai", "ollama")
        description: Human-readable description
        max_batch_size: Maximum texts per embed() call (default: 100)
        embedding_dimension: Output vector dimension (0 = unknown until first call)
    """

    @property
    def plugin_id(self) -> str: ...                    # EXISTING

    @property
    def description(self) -> str: ...                  # EXISTING

    @property
    def max_batch_size(self) -> int:                   # EXISTING
        return 100

    @property
    def embedding_dimension(self) -> int:              # EXISTING
        return 0

    async def embed(                                   # EXISTING
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Implementations MUST auto-split when len(texts) > max_batch_size
        and combine results transparently.

        Args:
            texts: Input text strings.
            model: Override model (optional; uses provider default if None).

        Returns:
            List of embedding vectors. Length matches input.
            Each vector has consistent dimensions.

        Raises:
            ValueError: If texts is empty.
            ConnectionError: If the embedding service is unreachable.
            AuthenticationError: If API key is invalid.
        """
        ...

    async def embed_single(                            # EXISTING
        self,
        text: str,
        model: str | None = None,
    ) -> list[float]:
        """Convenience wrapper for embedding a single text.

        Default implementation calls embed([text])[0].
        """
        ...

    def estimate_cost(                                 # NEW
        self,
        num_tokens: int,
    ) -> float:
        """Estimate the cost of embedding a given number of tokens.

        Args:
            num_tokens: Estimated total tokens to embed.

        Returns:
            Estimated cost in USD.
        """
        ...


# --- Registry ---

class EmbeddingProviderRegistry:                       # EXISTING
    """Registry for embedding provider plugins.

    Discovery: hiveflow.embeddings entry point group.
    """
    ...


# --- Entry Points (pyproject.toml) ---
# [project.entry-points."hiveflow.embeddings"]
# openai = "hiveflow.plugins.embeddings.openai_embeddings:OpenAIEmbeddingProvider"
