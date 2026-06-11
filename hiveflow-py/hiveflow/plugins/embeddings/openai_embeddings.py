"""OpenAI embedding provider plugin.

Uses the OpenAI SDK to generate text embeddings via the embeddings API.
Default model: text-embedding-3-small (1536 dimensions).

Requires:
    openai>=1.52.0 (core dependency, already installed)
    OPENAI_API_KEY environment variable
"""

import os

import structlog

from hiveflow.plugins.embeddings import EmbeddingProvider

logger = structlog.get_logger(__name__)

# Pricing per million tokens (text-embedding-3-small)
_COST_PER_MILLION_TOKENS = 0.02
_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSION = 1536


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider using the embeddings API."""

    @property
    def plugin_id(self) -> str:
        return "openai"

    @property
    def description(self) -> str:
        return "OpenAI text embeddings (text-embedding-3-small)"

    @property
    def max_batch_size(self) -> int:
        return 100

    @property
    def embedding_dimension(self) -> int:
        return _DEFAULT_DIMENSION

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Generate embeddings via OpenAI API.

        Auto-splits batches exceeding max_batch_size and combines results.

        Args:
            texts: Texts to embed.
            model: Model override (default: text-embedding-3-small).

        Returns:
            List of embedding vectors.

        Raises:
            ValueError: If texts is empty.
            ImportError: If openai is not installed.
        """
        if not texts:
            raise ValueError("texts list cannot be empty")

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "openai is required for the OpenAI embedding provider. "
                "Install it with: pip install openai>=1.52.0"
            ) from None

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is required for OpenAI embeddings"
            )

        model_name = model or _DEFAULT_MODEL
        client = AsyncOpenAI(api_key=api_key)

        # Auto-split into batches
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.max_batch_size):
            batch = texts[i : i + self.max_batch_size]
            logger.debug(
                "embeddings.openai.batch",
                batch_index=i // self.max_batch_size,
                batch_size=len(batch),
                model=model_name,
            )

            response = await client.embeddings.create(
                model=model_name,
                input=batch,
            )

            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        logger.info(
            "embeddings.openai.complete",
            total=len(all_embeddings),
            model=model_name,
        )
        return all_embeddings

    def estimate_cost(self, num_tokens: int) -> float:
        """Estimate cost for embedding tokens.

        Based on text-embedding-3-small pricing: ~$0.02 per 1M tokens.

        Args:
            num_tokens: Estimated total tokens.

        Returns:
            Estimated cost in USD.
        """
        return (num_tokens / 1_000_000) * _COST_PER_MILLION_TOKENS
