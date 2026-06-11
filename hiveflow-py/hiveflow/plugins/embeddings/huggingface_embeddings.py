"""Hugging Face embedding provider — local transformer-based embeddings.

Uses the ``sentence-transformers`` library to run a transformer model
locally.  No API key, no network call after the initial model download
(models are cached in ``~/.cache/huggingface/``).

Default model: ``all-MiniLM-L6-v2`` (384 dimensions, ~80 MB, very fast).

Included as a core dependency — works out of the box.
"""

import structlog

from hiveflow.plugins.embeddings import EmbeddingProvider

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_DIMENSION = 384


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """Local embedding provider using sentence-transformers.

    Runs a transformer model on the CPU (or GPU if available) with no
    API key required.  The model is downloaded once and cached locally.
    Included as a core dependency.
    """

    def __init__(self) -> None:
        self._model = None  # lazy-loaded

    def _get_model(self, model_name: str | None = None):
        """Lazy-load the SentenceTransformer model."""
        name = model_name or _DEFAULT_MODEL
        if self._model is None or getattr(self._model, "_hf_model_name", None) != name:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for the huggingface embedding "
                    "provider but could not be imported. Reinstall hiveflow or run:\n\n"
                    "    uv add sentence-transformers>=3.3.1\n\n"
                    "Or switch to a zero-dependency provider:\n"
                    "    HIVEFLOW_EMBEDDING_PROVIDER=local"
                ) from None
            logger.info("embeddings.huggingface.loading", model=name)
            self._model = SentenceTransformer(name)
            self._model._hf_model_name = name  # tag for cache check
        return self._model

    @property
    def plugin_id(self) -> str:
        return "huggingface"

    @property
    def description(self) -> str:
        return f"Local transformer embeddings via sentence-transformers ({_DEFAULT_MODEL})"

    @property
    def max_batch_size(self) -> int:
        return 512

    @property
    def embedding_dimension(self) -> int:
        return _DEFAULT_DIMENSION

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Generate embeddings locally using a transformer model.

        Args:
            texts: Texts to embed.
            model: Optional model override (any sentence-transformers model).

        Returns:
            List of embedding vectors.

        Raises:
            ValueError: If texts is empty.
            ImportError: If sentence-transformers is not installed.
        """
        if not texts:
            raise ValueError("texts list cannot be empty")

        st_model = self._get_model(model)
        embeddings = st_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

        logger.debug(
            "embeddings.huggingface.complete",
            total=len(texts),
            model=model or _DEFAULT_MODEL,
            dimension=embeddings.shape[1],
        )
        return embeddings.tolist()

    def estimate_cost(self, _num_tokens: int) -> float:
        """Local embeddings are free."""
        return 0.0
