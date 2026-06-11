"""In-memory vector store plugin.

Refactored from SimpleVectorStore to conform to VectorStorePlugin interface.
Uses numpy for vectorized cosine similarity when available, with pure-Python fallback.
"""

from typing import Any

import structlog

from hiveflow.plugins.vector_stores import VectorStorePlugin

logger = structlog.get_logger(__name__)


def _cosine_similarity_pure(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity fallback."""
    dot: float = sum(x * y for x, y in zip(a, b))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


class MemoryVectorStore(VectorStorePlugin):
    """In-memory vector store with cosine similarity.

    Uses numpy for vectorized batch similarity when available,
    falling back to pure-Python implementation.

    The existing SimpleVectorStore remains available but deprecated.
    """

    @property
    def plugin_id(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return "In-memory vector store with cosine similarity"

    def __init__(self) -> None:
        self._vectors: list[list[float]] = []
        self._documents: list[dict[str, Any]] = []
        self._id_index: dict[str, int] = {}  # doc_id -> index

    async def add(
        self,
        vectors: list[list[float]],
        documents: list[dict[str, Any]],
    ) -> None:
        if len(vectors) != len(documents):
            raise ValueError("Vectors and documents must have same length")

        for doc in documents:
            if "doc_id" not in doc:
                raise ValueError("Each document must contain a 'doc_id' key")

        for vec, doc in zip(vectors, documents):
            doc_id = doc["doc_id"]
            if doc_id in self._id_index:
                # Upsert: update existing
                idx = self._id_index[doc_id]
                self._vectors[idx] = vec
                self._documents[idx] = doc
            else:
                # Insert new
                idx = len(self._vectors)
                self._vectors.append(vec)
                self._documents.append(doc)
                self._id_index[doc_id] = idx

        logger.debug("vector_store.memory.add", count=len(vectors), total=len(self._vectors))

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        _filters: dict[str, Any] | None = None,
    ) -> list[tuple[dict[str, Any], float]]:
        if not self._vectors:
            return []

        if _HAS_NUMPY:
            similarities = self._numpy_similarities(query_vector)
        else:
            similarities = [_cosine_similarity_pure(query_vector, vec) for vec in self._vectors]

        # Get top-k indices sorted by similarity descending
        indexed = sorted(enumerate(similarities), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in indexed[:top_k]:
            results.append((self._documents[idx], float(score)))
        return results

    def _numpy_similarities(self, query_vector: list[float]) -> list[float]:
        """Compute cosine similarities using numpy."""
        query = np.array(query_vector, dtype=np.float32)
        matrix = np.array(self._vectors, dtype=np.float32)

        # Normalize
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return [0.0] * len(self._vectors)
        query = query / query_norm

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        matrix = matrix / norms

        # Cosine similarity via dot product of normalized vectors
        similarities = matrix @ query
        return similarities.tolist()

    async def delete(self, doc_ids: list[str]) -> None:
        ids_to_remove = set(doc_ids) & set(self._id_index.keys())
        if not ids_to_remove:
            return

        # Rebuild without removed docs
        new_vectors: list[list[float]] = []
        new_documents: list[dict[str, Any]] = []
        new_index: dict[str, int] = {}

        for i, doc in enumerate(self._documents):
            if doc["doc_id"] not in ids_to_remove:
                new_index[doc["doc_id"]] = len(new_vectors)
                new_vectors.append(self._vectors[i])
                new_documents.append(doc)

        self._vectors = new_vectors
        self._documents = new_documents
        self._id_index = new_index

        logger.debug("vector_store.memory.delete", removed=len(ids_to_remove))

    async def clear(self) -> None:
        self._vectors.clear()
        self._documents.clear()
        self._id_index.clear()
        logger.debug("vector_store.memory.cleared")

    async def count(self) -> int:
        return len(self._vectors)
