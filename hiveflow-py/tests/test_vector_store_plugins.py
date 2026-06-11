"""Unit tests for vector store plugins (MemoryVectorStore, CollectionManager)."""

import pytest

from hiveflow.plugins.vector_stores import CollectionManager, VectorStorePlugin
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore


class TestMemoryVectorStore:
    """Tests for the in-memory vector store."""

    @pytest.fixture
    def store(self):
        return MemoryVectorStore()

    async def test_add_and_count(self, store):
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        docs = [{"doc_id": "a", "text": "first"}, {"doc_id": "b", "text": "second"}]
        await store.add(vectors, docs)
        assert await store.count() == 2

    async def test_search_returns_ranked_results(self, store):
        await store.add(
            [[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]],
            [
                {"doc_id": "x", "text": "x"},
                {"doc_id": "y", "text": "y"},
                {"doc_id": "z", "text": "z"},
            ],
        )
        results = await store.search([1.0, 0.0], top_k=2)
        assert len(results) == 2
        # First result should be most similar to [1, 0]
        assert results[0][0]["doc_id"] == "x"
        assert results[0][1] > results[1][1]

    async def test_search_empty_store(self, store):
        results = await store.search([1.0, 0.0])
        assert results == []

    async def test_upsert_updates_existing(self, store):
        await store.add([[1.0, 0.0]], [{"doc_id": "a", "text": "v1"}])
        await store.add([[0.0, 1.0]], [{"doc_id": "a", "text": "v2"}])
        assert await store.count() == 1
        results = await store.search([0.0, 1.0], top_k=1)
        assert results[0][0]["text"] == "v2"

    async def test_delete_removes_documents(self, store):
        await store.add(
            [[1.0, 0.0], [0.0, 1.0]],
            [{"doc_id": "a"}, {"doc_id": "b"}],
        )
        await store.delete(["a"])
        assert await store.count() == 1
        results = await store.search([1.0, 0.0], top_k=5)
        assert len(results) == 1
        assert results[0][0]["doc_id"] == "b"

    async def test_delete_nonexistent_is_silent(self, store):
        await store.add([[1.0, 0.0]], [{"doc_id": "a"}])
        await store.delete(["nonexistent"])
        assert await store.count() == 1

    async def test_clear_removes_all(self, store):
        await store.add(
            [[1.0, 0.0], [0.0, 1.0]],
            [{"doc_id": "a"}, {"doc_id": "b"}],
        )
        await store.clear()
        assert await store.count() == 0

    async def test_add_mismatched_lengths_raises(self, store):
        with pytest.raises(ValueError, match="same length"):
            await store.add([[1.0]], [{"doc_id": "a"}, {"doc_id": "b"}])

    async def test_add_missing_doc_id_raises(self, store):
        with pytest.raises(ValueError, match="doc_id"):
            await store.add([[1.0]], [{"text": "no id"}])

    def test_plugin_properties(self, store):
        assert store.plugin_id == "memory"
        assert isinstance(store.description, str)

    async def test_cosine_similarity_correctness(self, store):
        """Verify cosine similarity produces expected ordering."""
        await store.add(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.5, 0.5, 0.0]],
            [{"doc_id": "a"}, {"doc_id": "b"}, {"doc_id": "c"}],
        )
        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        ids = [r[0]["doc_id"] for r in results]
        # a should be first (exact match), c second (partial), b last (orthogonal)
        assert ids[0] == "a"
        assert ids[2] == "b"


class TestCollectionManager:
    """Tests for collection namespacing and lifecycle."""

    async def test_collection_name(self):
        store = MemoryVectorStore()
        mgr = CollectionManager(store, collection_prefix="wf_", persist=False)
        assert mgr.collection_name("session-123") == "wf_session-123"

    async def test_ephemeral_cleanup_clears_store(self):
        store = MemoryVectorStore()
        await store.add([[1.0]], [{"doc_id": "a"}])
        mgr = CollectionManager(store, persist=False)
        await mgr.cleanup()
        assert await store.count() == 0

    async def test_persistent_cleanup_preserves_store(self):
        store = MemoryVectorStore()
        await store.add([[1.0]], [{"doc_id": "a"}])
        mgr = CollectionManager(store, persist=True)
        await mgr.cleanup()
        assert await store.count() == 1

    async def test_store_property(self):
        store = MemoryVectorStore()
        mgr = CollectionManager(store)
        assert mgr.store is store
