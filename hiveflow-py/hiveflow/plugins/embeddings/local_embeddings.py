"""Local embedding provider — offline, zero-API, numpy-only.

Generates deterministic text embeddings using character and word n-gram
feature hashing projected into a fixed-dimension vector space.  No model
download, no API key, no network call.

This is the zero-dependency fallback provider.  The default provider is
``huggingface`` which uses sentence-transformers (core dependency) for
higher-quality embeddings.

The feature-hashing approach is adequate for:
  - document chunk retrieval / semantic search within a workflow
  - source-curation relevance scoring
  - any use case where you want *fast*, *free*, *offline* similarity
    with zero dependencies beyond numpy
"""

import hashlib
import re

import numpy as np
import structlog

from hiveflow.plugins.embeddings import EmbeddingProvider

logger = structlog.get_logger(__name__)

_DEFAULT_DIMENSION = 384  # Compact but effective


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, return word tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _ngrams(tokens: list[str], n: int) -> list[str]:
    """Generate token-level n-grams (bigrams, trigrams, …)."""
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _char_ngrams(text: str, n: int) -> list[str]:
    """Generate character-level n-grams from the raw (lowered) text."""
    lowered = text.lower()
    return [lowered[i : i + n] for i in range(len(lowered) - n + 1)]


def _hash_feature(feature: str, dim: int) -> tuple[int, float]:
    """Hash a feature string to a (bucket_index, sign) pair."""
    h = hashlib.md5(feature.encode("utf-8"), usedforsecurity=False).hexdigest()
    bucket = int(h[:8], 16) % dim
    sign = 1.0 if int(h[8:10], 16) % 2 == 0 else -1.0
    return bucket, sign


def _embed_text(text: str, dim: int) -> list[float]:
    """Embed a single text into a fixed-dimension vector.

    Combines word unigrams, bigrams, and character 3/4-grams via
    feature hashing, then L2-normalises.
    """
    vec = np.zeros(dim, dtype=np.float64)

    tokens = _tokenize(text)

    # Word unigrams (weight 1.0)
    for token in tokens:
        idx, sign = _hash_feature(f"w1:{token}", dim)
        vec[idx] += sign * 1.0

    # Word bigrams (weight 1.5 — phrase overlap is a stronger signal)
    for bg in _ngrams(tokens, 2):
        idx, sign = _hash_feature(f"w2:{bg}", dim)
        vec[idx] += sign * 1.5

    # Character 3-grams (weight 0.3 — captures sub-word similarity)
    for cng in _char_ngrams(text, 3):
        idx, sign = _hash_feature(f"c3:{cng}", dim)
        vec[idx] += sign * 0.3

    # Character 4-grams (weight 0.2)
    for cng in _char_ngrams(text, 4):
        idx, sign = _hash_feature(f"c4:{cng}", dim)
        vec[idx] += sign * 0.2

    # L2 normalise so cosine similarity = dot product
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm

    return vec.tolist()


class LocalEmbeddingProvider(EmbeddingProvider):
    """Offline embedding provider using feature hashing (numpy only).

    Produces fixed-dimension vectors suitable for cosine similarity.
    No API key, no model download, no network access required.
    """

    @property
    def plugin_id(self) -> str:
        return "local"

    @property
    def description(self) -> str:
        return "Local offline embeddings via feature hashing (numpy)"

    @property
    def max_batch_size(self) -> int:
        return 10_000  # CPU-only, no API limits

    @property
    def embedding_dimension(self) -> int:
        return _DEFAULT_DIMENSION

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,  # noqa: ARG002
    ) -> list[list[float]]:
        """Generate embeddings locally.

        The *model* parameter is accepted for interface compatibility
        but ignored — this provider uses a single deterministic algorithm.

        Args:
            texts: Texts to embed.
            model: Ignored (kept for API compatibility).

        Returns:
            List of embedding vectors.

        Raises:
            ValueError: If texts is empty.
        """
        if not texts:
            raise ValueError("texts list cannot be empty")

        dim = _DEFAULT_DIMENSION
        embeddings = [_embed_text(t, dim) for t in texts]

        logger.debug(
            "embeddings.local.complete",
            total=len(embeddings),
            dimension=dim,
        )
        return embeddings

    def estimate_cost(self, _num_tokens: int) -> float:
        """Local embeddings are free."""
        return 0.0
