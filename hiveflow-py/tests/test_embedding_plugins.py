"""Unit tests for embedding provider plugins (HuggingFace + Local + OpenAI)."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.embeddings import EmbeddingProvider


class TestOpenAIEmbeddingProvider:
    """Tests for the OpenAI embedding provider plugin."""

    @pytest.fixture
    def mock_openai_response(self):
        """Mock OpenAI embeddings.create response."""
        mock_data_item_1 = MagicMock()
        mock_data_item_1.embedding = [0.1, 0.2, 0.3]
        mock_data_item_2 = MagicMock()
        mock_data_item_2.embedding = [0.4, 0.5, 0.6]

        mock_response = MagicMock()
        mock_response.data = [mock_data_item_1, mock_data_item_2]
        mock_response.usage = MagicMock(total_tokens=20)
        return mock_response

    async def test_embed_returns_vectors(self, mock_openai_response):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider()
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_openai_response)

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI = MagicMock(return_value=mock_client)

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.dict("sys.modules", {"openai": mock_openai_module}),
        ):
            results = await provider.embed(["text one", "text two"])

        assert len(results) == 2
        assert results[0] == [0.1, 0.2, 0.3]
        assert results[1] == [0.4, 0.5, 0.6]

    async def test_embed_auto_splits_batches(self):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider()

        # Create mock responses for 2 batches
        def make_response(count):
            items = []
            for i in range(count):
                item = MagicMock()
                item.embedding = [float(i)] * 3
                items.append(item)
            resp = MagicMock()
            resp.data = items
            return resp

        mock_client = AsyncMock()
        # First batch: 100 items, second batch: 10 items
        mock_client.embeddings.create = AsyncMock(
            side_effect=[make_response(100), make_response(10)]
        )

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI = MagicMock(return_value=mock_client)

        texts = [f"text {i}" for i in range(110)]

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.dict("sys.modules", {"openai": mock_openai_module}),
        ):
            results = await provider.embed(texts)

        assert len(results) == 110
        assert mock_client.embeddings.create.call_count == 2

    async def test_embed_empty_texts_raises(self):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider()
        with pytest.raises(ValueError, match="empty"):
            await provider.embed([])

    async def test_embed_missing_api_key_raises(self):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        mock_openai_module = MagicMock()
        provider = OpenAIEmbeddingProvider()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.dict("sys.modules", {"openai": mock_openai_module}),
            pytest.raises(ValueError, match="OPENAI_API_KEY"),
        ):
            await provider.embed(["test"])

    async def test_embed_single_convenience(self, mock_openai_response):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        # Adjust mock for single item
        mock_data_item = MagicMock()
        mock_data_item.embedding = [0.7, 0.8, 0.9]
        single_response = MagicMock()
        single_response.data = [mock_data_item]

        provider = OpenAIEmbeddingProvider()
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=single_response)

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI = MagicMock(return_value=mock_client)

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.dict("sys.modules", {"openai": mock_openai_module}),
        ):
            result = await provider.embed_single("single text")

        assert result == [0.7, 0.8, 0.9]

    def test_estimate_cost(self):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider()
        # 1M tokens at $0.02/1M = $0.02
        assert provider.estimate_cost(1_000_000) == pytest.approx(0.02)
        # 500K tokens = $0.01
        assert provider.estimate_cost(500_000) == pytest.approx(0.01)
        # 0 tokens = $0.0
        assert provider.estimate_cost(0) == 0.0

    def test_plugin_properties(self):
        from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider()
        assert provider.plugin_id == "openai"
        assert provider.max_batch_size == 100
        assert provider.embedding_dimension == 1536


class TestLocalEmbeddingProvider:
    """Tests for the local (offline) embedding provider."""

    def _provider(self):
        from hiveflow.plugins.embeddings.local_embeddings import LocalEmbeddingProvider
        return LocalEmbeddingProvider()

    def test_plugin_properties(self):
        p = self._provider()
        assert p.plugin_id == "local"
        assert p.embedding_dimension == 384
        assert p.max_batch_size == 10_000
        assert "offline" in p.description.lower() or "local" in p.description.lower()

    async def test_embed_returns_correct_shape(self):
        p = self._provider()
        results = await p.embed(["hello world", "foo bar"])
        assert len(results) == 2
        assert all(len(v) == 384 for v in results)

    async def test_embed_single(self):
        p = self._provider()
        vec = await p.embed_single("test text")
        assert len(vec) == 384

    async def test_embed_empty_raises(self):
        p = self._provider()
        with pytest.raises(ValueError, match="empty"):
            await p.embed([])

    async def test_deterministic(self):
        """Same input always produces identical vectors."""
        p = self._provider()
        v1 = await p.embed(["determinism check"])
        v2 = await p.embed(["determinism check"])
        assert v1 == v2

    async def test_similar_texts_closer_than_dissimilar(self):
        """Semantically related texts should have higher cosine similarity."""
        import numpy as np

        p = self._provider()
        vecs = await p.embed([
            "machine learning algorithms",
            "deep learning neural networks",
            "chocolate cake recipe baking",
        ])
        v_ml, v_dl, v_cake = (np.array(v) for v in vecs)

        sim_related = float(np.dot(v_ml, v_dl))
        sim_unrelated = float(np.dot(v_ml, v_cake))
        assert sim_related > sim_unrelated, (
            f"Related similarity ({sim_related:.4f}) should exceed "
            f"unrelated similarity ({sim_unrelated:.4f})"
        )

    async def test_vectors_are_normalized(self):
        """Output vectors should be L2-normalized (unit length)."""
        import numpy as np

        p = self._provider()
        vecs = await p.embed(["some text", "another text", "third one"])
        for vec in vecs:
            norm = np.linalg.norm(vec)
            assert abs(norm - 1.0) < 1e-6, f"Expected unit norm, got {norm}"

    def test_estimate_cost_is_zero(self):
        p = self._provider()
        assert p.estimate_cost(1_000_000) == 0.0

    def test_is_embedding_provider_subclass(self):
        p = self._provider()
        assert isinstance(p, EmbeddingProvider)


class TestHuggingFaceEmbeddingProvider:
    """Tests for the HuggingFace embedding provider (mocked sentence-transformers)."""

    def _provider(self):
        from hiveflow.plugins.embeddings.huggingface_embeddings import HuggingFaceEmbeddingProvider
        return HuggingFaceEmbeddingProvider()

    def test_plugin_properties(self):
        p = self._provider()
        assert p.plugin_id == "huggingface"
        assert p.embedding_dimension == 384
        assert p.max_batch_size == 512
        assert "sentence-transformers" in p.description.lower() or "transformer" in p.description.lower()

    def test_estimate_cost_is_zero(self):
        p = self._provider()
        assert p.estimate_cost(1_000_000) == 0.0

    def test_is_embedding_provider_subclass(self):
        p = self._provider()
        assert isinstance(p, EmbeddingProvider)

    async def test_embed_returns_vectors_mocked(self):
        """Embed returns correct shape when sentence-transformers is mocked."""
        import numpy as np
        from hiveflow.plugins.embeddings.huggingface_embeddings import HuggingFaceEmbeddingProvider

        p = HuggingFaceEmbeddingProvider()

        mock_model = MagicMock()
        mock_model.encode = MagicMock(
            return_value=np.random.randn(2, 384).astype(np.float32)
        )

        mock_st_module = MagicMock()
        mock_st_module.SentenceTransformer = MagicMock(return_value=mock_model)

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module}):
            results = await p.embed(["hello", "world"])

        assert len(results) == 2
        assert all(len(v) == 384 for v in results)
        mock_model.encode.assert_called_once()

    async def test_embed_empty_raises(self):
        p = self._provider()
        with pytest.raises(ValueError, match="empty"):
            await p.embed([])

    def test_missing_library_gives_clear_error(self):
        """ImportError message should mention uv add and the fallback provider."""
        from hiveflow.plugins.embeddings.huggingface_embeddings import HuggingFaceEmbeddingProvider

        p = HuggingFaceEmbeddingProvider()

        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="sentence-transformers"):
                p._get_model()
