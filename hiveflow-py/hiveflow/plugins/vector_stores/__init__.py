"""Vector Store Plugin System - Pluggable vector storage backends.

Vector stores persist and search embedding vectors for semantic
retrieval. Each workflow run can use isolated collection namespaces.

Built-in backends:
  memory - In-memory store with cosine similarity (default)

Additional backends discovered via the 'hiveflow.vector_stores' entry point group.
"""

from abc import abstractmethod
from typing import Any

import structlog

from hiveflow.core.registry import BasePlugin, PluginRegistry

logger = structlog.get_logger(__name__)


class VectorStorePlugin(BasePlugin):
    """Base class for vector store plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Store identifier (e.g., 'memory', 'chroma')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @abstractmethod
    async def add(
        self,
        vectors: list[list[float]],
        documents: list[dict[str, Any]],
    ) -> None:
        """Add vectors and associated documents.

        Each document dict MUST contain a "doc_id" key for identity.
        If a doc_id already exists, the entry is updated (upsert).

        Args:
            vectors: Embedding vectors.
            documents: Associated document metadata dicts.

        Raises:
            ValueError: If vectors and documents have different lengths.
            ValueError: If any document is missing a "doc_id" key.
        """
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        """Search for most similar documents.

        Args:
            query_vector: Query embedding vector.
            top_k: Maximum number of results.
            filters: Optional metadata filters (backend-specific).

        Returns:
            List of (document, similarity_score) tuples,
            sorted by score descending.
        """
        ...

    @abstractmethod
    async def delete(self, doc_ids: list[str]) -> None:
        """Remove documents by their doc_id.

        Silently ignores IDs that do not exist.

        Args:
            doc_ids: Document IDs to remove.
        """
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove all stored vectors and documents."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return the number of stored documents."""
        ...


class VectorStoreRegistry(PluginRegistry["VectorStorePlugin"]):
    """Registry for vector store plugins.

    Discovers stores from:
    - Python entry points under 'hiveflow.vector_stores'
    - Drop-in directory
    """

    def __init__(self, drop_in_dir: str | None = "vector_stores") -> None:
        super().__init__(
            entry_point_group="hiveflow.vector_stores",
            drop_in_dir=drop_in_dir,
        )


class CollectionManager:
    """Manages collection namespacing and lifecycle.

    Collections are namespaced by "{collection_prefix}{session_id}".
    Ephemeral collections are cleared on workflow completion.
    Persistent collections survive across runs.
    """

    def __init__(
        self,
        store: VectorStorePlugin,
        collection_prefix: str = "workflow_",
        persist: bool = False,
    ) -> None:
        self._store = store
        self._collection_prefix = collection_prefix
        self._persist = persist

    @property
    def store(self) -> VectorStorePlugin:
        """The underlying vector store plugin."""
        return self._store

    def collection_name(self, session_id: str) -> str:
        """Return the namespaced collection name."""
        return f"{self._collection_prefix}{session_id}"

    async def cleanup(self) -> None:
        """Clear the collection if ephemeral (persist=False).

        Best-effort: logs a warning on failure rather than raising.
        """
        if self._persist:
            return
        try:
            await self._store.clear()
            logger.info("vector_store.collection_cleared", persist=self._persist)
        except Exception:
            logger.warning("vector_store.cleanup_failed", exc_info=True)
