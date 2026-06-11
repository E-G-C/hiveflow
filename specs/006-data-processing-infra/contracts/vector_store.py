"""Vector Store Plugin Interface Contract.

Defines the public contract for vector store plugins. Implementations
must inherit from VectorStorePlugin and register via the
hiveflow.vector_stores entry point group.

NOTE: SimpleVectorStore already exists in hiveflow/plugins/embeddings/__init__.py.
It will be refactored to conform to VectorStorePlugin and moved to
hiveflow/plugins/vector_stores/memory_store.py.
Changes marked with # EXISTING, # REFACTORED, or # NEW.
"""

from typing import Any


# --- Plugin Interface ---

class VectorStorePlugin:                                  # NEW
    """Base class for vector store plugins.

    Properties:
        plugin_id: Unique identifier (e.g., "memory", "chroma")
        description: Human-readable description
    """

    @property
    def plugin_id(self) -> str: ...                       # NEW

    @property
    def description(self) -> str: ...                     # NEW

    async def add(                                        # NEW
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

    async def search(                                     # NEW
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

    async def delete(                                     # NEW
        self,
        doc_ids: list[str],
    ) -> None:
        """Remove documents by their doc_id.

        Args:
            doc_ids: Document IDs to remove.

        Silently ignores IDs that do not exist.
        """
        ...

    async def clear(self) -> None:                        # NEW
        """Remove all stored vectors and documents."""
        ...

    async def count(self) -> int:                         # NEW
        """Return the number of stored documents."""
        ...


# --- Collection Management ---

class CollectionManager:                                  # NEW
    """Manages collection namespacing and lifecycle.

    Collections are namespaced by "{collection_prefix}_{session_id}".
    Ephemeral collections are cleared on workflow completion.
    Persistent collections survive across runs.

    This is NOT a plugin interface — it is framework-internal and
    wraps a VectorStorePlugin instance.
    """

    def __init__(
        self,
        store: VectorStorePlugin,
        collection_prefix: str = "workflow_",
        persist: bool = False,
    ) -> None:
        """
        Args:
            store: The underlying vector store plugin.
            collection_prefix: Namespace prefix for collections.
            persist: If False, collection is cleared on cleanup().
        """
        ...

    def collection_name(self, session_id: str) -> str:
        """Return the namespaced collection name.

        Returns:
            "{collection_prefix}{session_id}"
        """
        ...

    async def cleanup(self) -> None:
        """Clear the collection if ephemeral (persist=False).

        Best-effort: logs a warning on failure rather than raising.
        """
        ...


# --- Registry ---

class VectorStoreRegistry:                                # NEW
    """Registry for vector store plugins.

    Discovery: hiveflow.vector_stores entry point group.
    """
    ...


# --- Refactored Existing Class ---

class MemoryVectorStore(VectorStorePlugin):               # REFACTORED from SimpleVectorStore
    """In-memory vector store using cosine similarity.

    Refactored from SimpleVectorStore to conform to VectorStorePlugin.

    Differences from SimpleVectorStore:
        - All methods are async
        - add() validates doc_id presence
        - delete() supports removal by doc_id
        - count() returns document count
        - search() supports optional filters parameter (ignored for in-memory)
        - Uses numpy for vectorized cosine similarity when available,
          falling back to pure-Python implementation

    The existing SimpleVectorStore remains available but deprecated.
    """

    plugin_id = "memory"
    description = "In-memory vector store with cosine similarity"

    ...


# --- Entry Points (pyproject.toml) ---
# [project.entry-points."hiveflow.vector_stores"]
# memory = "hiveflow.plugins.vector_stores.memory_store:MemoryVectorStore"
