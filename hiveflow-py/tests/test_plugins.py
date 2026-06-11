"""Tests for Error Isolation, Rate Limiting, and Data Processing Plugins."""

import asyncio

import pytest

from hiveflow.core.errors import (
    BulkheadSemaphore,
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    with_timeout,
)
from hiveflow.core.ratelimit import (
    ConcurrencyLimiter,
    ProviderRateLimiter,
    TokenBucketRateLimiter,
)
from hiveflow.plugins.documents import Document, PlainTextLoader, chunk_text
from hiveflow.plugins.embeddings import SimpleVectorStore, _cosine_similarity
from hiveflow.plugins.publishers import MarkdownPublisher
from hiveflow.plugins.retrievers import RetrieverRegistry, SearchResult
from hiveflow.plugins.scrapers import ScrapedContent

# --- Circuit Breaker Tests ---


class TestCircuitBreaker:
    async def test_closed_normal_operation(self):
        breaker = CircuitBreaker(failure_threshold=3)

        async def success() -> str:
            return "ok"

        result = await breaker.call(success)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    async def test_opens_after_threshold(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=100.0)

        async def fail() -> str:
            raise RuntimeError("fail")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(fail)

        assert breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerError):
            await breaker.call(fail)

    async def test_resets_on_success(self):
        breaker = CircuitBreaker(failure_threshold=3)

        async def fail() -> str:
            raise RuntimeError("fail")

        async def success() -> str:
            return "ok"

        # One failure
        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        # Success resets counter
        result = await breaker.call(success)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    async def test_manual_reset(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=100.0)

        async def fail() -> str:
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        assert breaker.state == CircuitState.OPEN
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED


class TestWithTimeout:
    async def test_completes_within_timeout(self):
        async def fast() -> str:
            return "done"

        result = await with_timeout(fast(), timeout_seconds=5.0)
        assert result == "done"

    async def test_timeout_returns_default(self):
        async def slow() -> str:
            await asyncio.sleep(10)
            return "done"

        result = await with_timeout(slow(), timeout_seconds=0.01, default="timeout")
        assert result == "timeout"


class TestBulkheadSemaphore:
    async def test_limits_concurrency(self):
        bulkhead = BulkheadSemaphore(max_concurrent=2)
        assert bulkhead.available == 2

        async def task() -> str:
            return "done"

        result = await bulkhead.call(task)
        assert result == "done"
        assert bulkhead.active_count == 0

    async def test_tracks_active(self):
        bulkhead = BulkheadSemaphore(max_concurrent=5)
        await bulkhead.acquire()
        assert bulkhead.active_count == 1
        assert bulkhead.available == 4
        bulkhead.release()
        assert bulkhead.active_count == 0


# --- Rate Limiting Tests ---


class TestTokenBucketRateLimiter:
    async def test_acquire_within_limit(self):
        limiter = TokenBucketRateLimiter(max_rate=100, per_seconds=1.0)
        # Should not block for small number of requests
        await limiter.acquire()
        assert limiter.available_tokens < 100

    async def test_available_tokens(self):
        limiter = TokenBucketRateLimiter(max_rate=10, per_seconds=1.0)
        initial = limiter.available_tokens
        await limiter.acquire(5)
        assert limiter.available_tokens < initial


class TestConcurrencyLimiter:
    async def test_limits_concurrent(self):
        limiter = ConcurrencyLimiter(max_concurrent=2)

        async def task() -> str:
            return "result"

        result = await limiter.run(task)
        assert result == "result"
        assert limiter.active_count == 0

    async def test_context_manager(self):
        limiter = ConcurrencyLimiter(max_concurrent=3)

        async with limiter:
            assert limiter.active_count == 1

        assert limiter.active_count == 0


class TestProviderRateLimiter:
    async def test_configure_and_acquire(self):
        limiter = ProviderRateLimiter()
        limiter.configure("openai", requests_per_minute=100, tokens_per_minute=100000)

        # Should not raise
        await limiter.acquire_request("openai")
        await limiter.acquire_tokens("openai", 100)

    async def test_unconfigured_provider_passes(self):
        limiter = ProviderRateLimiter()
        # Unconfigured provider should not block
        await limiter.acquire_request("unknown")
        await limiter.acquire_tokens("unknown", 1000)


# --- Embedding & Vector Store Tests ---


class TestSimpleVectorStore:
    def test_add_and_search(self):
        store = SimpleVectorStore()
        store.add(
            vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            documents=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
        )

        results = store.search([1.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0][0]["id"] == "a"
        assert results[0][1] == pytest.approx(1.0)

    def test_empty_search(self):
        store = SimpleVectorStore()
        results = store.search([1.0, 0.0], top_k=5)
        assert results == []

    def test_size_and_clear(self):
        store = SimpleVectorStore()
        store.add([[1.0]], [{"id": 1}])
        assert store.size == 1
        store.clear()
        assert store.size == 0

    def test_mismatched_lengths(self):
        store = SimpleVectorStore()
        with pytest.raises(ValueError):
            store.add([[1.0]], [{"id": 1}, {"id": 2}])


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 0]) == 0.0


# --- Publisher Tests ---


class TestMarkdownPublisher:
    async def test_publish_basic(self, tmp_path):
        publisher = MarkdownPublisher()
        result = await publisher.publish(
            "# Hello\nWorld",
            tmp_path / "test.md",
        )
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "# Hello" in content

    async def test_publish_with_metadata(self, tmp_path):
        publisher = MarkdownPublisher()
        result = await publisher.publish(
            "Content here",
            tmp_path / "test.md",
            metadata={"title": "Test", "author": "Bot"},
        )
        content = result.read_text(encoding="utf-8")
        assert "---" in content
        assert "title: Test" in content

    async def test_auto_extension(self, tmp_path):
        publisher = MarkdownPublisher()
        result = await publisher.publish("content", tmp_path / "no_ext")
        assert result.suffix == ".md"

    def test_properties(self):
        publisher = MarkdownPublisher()
        assert publisher.plugin_id == "markdown"
        assert publisher.output_extension == ".md"


class TestMarkdownPublisherPayload:
    """Tests for MarkdownPublisher.publish_payload()."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    async def test_basic_publish_payload(self, tmp_path):
        publisher = MarkdownPublisher()
        payload = self._make_payload()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        assert result.exists()
        text = result.read_text(encoding="utf-8")
        assert "# Test Report" in text
        assert "title: Test Report" in text  # frontmatter

    async def test_toc_generated_from_sections(self, tmp_path):
        from hiveflow.core.result_payload import PayloadSection
        payload = self._make_payload(
            sections=[
                PayloadSection(section_id="intro", title="Introduction", content="Intro text", order=0),
                PayloadSection(section_id="findings", title="Findings", content="Data here", order=1),
            ],
        )
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        text = result.read_text(encoding="utf-8")
        assert "## Table of Contents" in text
        assert "[Introduction]" in text
        assert "[Findings]" in text

    async def test_references_rendered(self, tmp_path):
        from hiveflow.core.citations import Citation
        payload = self._make_payload(
            references=[
                Citation(url="https://example.com", title="Example", author="Smith"),
                Citation(url="https://other.com", title="Other"),
            ],
        )
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        text = result.read_text(encoding="utf-8")
        assert "## References" in text
        assert "[Example](https://example.com)" in text
        assert "Smith" in text

    async def test_cost_appendix(self, tmp_path):
        from hiveflow.core.cost import AgentCostSummary, WorkflowCostReport
        cost = WorkflowCostReport(
            total_tokens=1500,
            total_prompt_tokens=1000,
            total_completion_tokens=500,
            total_estimated_cost_usd=0.0125,
            agent_summaries={
                "researcher": AgentCostSummary(
                    agent_id="researcher", total_tokens=1000, call_count=3,
                ),
            },
        )
        payload = self._make_payload(cost_summary=cost)
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        text = result.read_text(encoding="utf-8")
        assert "## Appendix: Cost & Token Usage" in text
        assert "1,500" in text
        assert "researcher" in text

    async def test_empty_payload_raises(self, tmp_path):
        from hiveflow.core.result_payload import ResultPayload
        payload = ResultPayload(title="Empty", content="", sections=[])
        publisher = MarkdownPublisher()
        with pytest.raises(ValueError, match="empty"):
            await publisher.publish_payload(payload, tmp_path / "out.md")

    async def test_directory_auto_creation(self, tmp_path):
        payload = self._make_payload()
        publisher = MarkdownPublisher()
        deep_path = tmp_path / "a" / "b" / "c" / "out.md"
        result = await publisher.publish_payload(payload, deep_path)
        assert result.exists()

    async def test_auto_extension(self, tmp_path):
        payload = self._make_payload()
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "no_ext")
        assert result.suffix == ".md"

    async def test_actions_rendered(self, tmp_path):
        from hiveflow.core.result_payload import ActionRecord
        payload = self._make_payload(
            actions=[
                ActionRecord(
                    action_id="a1", action_type="email",
                    description="Sent notification", status="completed",
                    agent_id="notifier",
                ),
            ],
        )
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        text = result.read_text(encoding="utf-8")
        assert "## Actions Taken" in text
        assert "Sent notification" in text


    async def test_duplicate_h1_stripped(self, tmp_path):
        """Content starting with '# Title' should not produce two H1 headers."""
        payload = self._make_payload(
            title="My Report",
            content="# My Report\n\nBody content here",
        )
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        text = result.read_text(encoding="utf-8")
        h1_count = text.count("\n# ")
        # The first '# ' may be at the start (after frontmatter), so count all occurrences
        all_h1 = [line for line in text.splitlines() if line.startswith("# ")]
        assert len(all_h1) == 1, f"Expected 1 H1 header, got {len(all_h1)}: {all_h1}"
        assert "Body content here" in text

    async def test_section_content_h1_stripped(self, tmp_path):
        """Section content starting with '# Title' gets the H1 stripped."""
        from hiveflow.core.result_payload import PayloadSection
        payload = self._make_payload(
            title="Report",
            sections=[
                PayloadSection(
                    section_id="s1", title="Analysis", order=0,
                    content="# Analysis Report\n\nDetailed analysis...",
                ),
            ],
        )
        publisher = MarkdownPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.md")
        text = result.read_text(encoding="utf-8")
        # Should not contain two different H1 lines
        all_h1 = [line for line in text.splitlines() if line.startswith("# ")]
        assert len(all_h1) == 1
        assert "Detailed analysis..." in text


# --- JSON Publisher Tests ---


class TestJSONPublisher:
    """Tests for JSONPublisher."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    async def test_basic_publish_payload(self, tmp_path):
        import json

        from hiveflow.plugins.publishers.json_publisher import JSONPublisher
        publisher = JSONPublisher()
        payload = self._make_payload()
        result = await publisher.publish_payload(payload, tmp_path / "out.json")
        assert result.exists()
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["title"] == "Test Report"
        assert data["content"] == "Body content"

    async def test_round_trip_fidelity(self, tmp_path):
        import json

        from hiveflow.core.citations import Citation
        from hiveflow.core.result_payload import PayloadSection
        from hiveflow.plugins.publishers.json_publisher import JSONPublisher
        payload = self._make_payload(
            sections=[
                PayloadSection(section_id="s1", title="Section 1", content="text", order=0),
            ],
            references=[Citation(url="https://x.com", title="X")],
            metadata={"date": "2026-02-20"},
        )
        publisher = JSONPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.json")
        data = json.loads(result.read_text(encoding="utf-8"))
        assert len(data["sections"]) == 1
        assert data["sections"][0]["section_id"] == "s1"
        assert len(data["references"]) == 1
        assert data["metadata"]["date"] == "2026-02-20"

    async def test_empty_fields(self, tmp_path):
        import json

        from hiveflow.plugins.publishers.json_publisher import JSONPublisher
        payload = self._make_payload()
        publisher = JSONPublisher()
        result = await publisher.publish_payload(payload, tmp_path / "out.json")
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["sections"] == []
        assert data["references"] == []
        assert data["actions"] == []

    async def test_auto_extension(self, tmp_path):
        from hiveflow.plugins.publishers.json_publisher import JSONPublisher
        publisher = JSONPublisher()
        payload = self._make_payload()
        result = await publisher.publish_payload(payload, tmp_path / "no_ext")
        assert result.suffix == ".json"

    def test_properties(self):
        from hiveflow.plugins.publishers.json_publisher import JSONPublisher
        publisher = JSONPublisher()
        assert publisher.plugin_id == "json"
        assert publisher.output_extension == ".json"


# --- PDF Publisher Tests ---


class TestPDFPublisher:
    """Tests for PDFPublisher (mocking pypandoc)."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    async def test_publish_payload_calls_pypandoc(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.pdf_publisher import PDFPublisher

        publisher = PDFPublisher()
        payload = self._make_payload()

        mock_convert = MagicMock()
        with patch("hiveflow.plugins.publishers.pdf_publisher.pypandoc", create=True) as mock_mod:
            mock_mod.convert_text = mock_convert
            # pypandoc.convert_text is called in a thread; patch the import inside
            with patch.dict("sys.modules", {"pypandoc": mock_mod}):
                await publisher.publish_payload(payload, tmp_path / "out.pdf")

        mock_convert.assert_called_once()
        args = mock_convert.call_args
        assert args[0][1] == "pdf"
        assert args[1]["format"] == "md"
        assert "Test Report" in args[0][0]

    async def test_graceful_error_when_pypandoc_missing(self, tmp_path):
        from unittest.mock import patch

        from hiveflow.plugins.publishers.pdf_publisher import PDFPublisher

        publisher = PDFPublisher()
        payload = self._make_payload()

        with patch.dict("sys.modules", {"pypandoc": None}), pytest.raises(Exception):
            await publisher.publish_payload(payload, tmp_path / "out.pdf")

    def test_properties(self):
        from hiveflow.plugins.publishers.pdf_publisher import PDFPublisher
        publisher = PDFPublisher()
        assert publisher.plugin_id == "pdf"
        assert publisher.output_extension == ".pdf"


# --- DOCX Publisher Tests ---


class TestDOCXPublisher:
    """Tests for DOCXPublisher (mocking pypandoc)."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    async def test_publish_payload_calls_pypandoc_docx(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher

        publisher = DOCXPublisher()
        payload = self._make_payload()

        mock_convert = MagicMock()
        with patch.dict("sys.modules", {"pypandoc": MagicMock(convert_text=mock_convert)}):
            await publisher.publish_payload(payload, tmp_path / "out.docx")

        mock_convert.assert_called_once()
        args = mock_convert.call_args
        assert args[0][1] == "docx"
        assert args[1]["format"] == "md"

    async def test_graceful_error_when_pypandoc_missing(self, tmp_path):
        from unittest.mock import patch

        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher

        publisher = DOCXPublisher()
        payload = self._make_payload()

        with patch.dict("sys.modules", {"pypandoc": None}), pytest.raises(Exception):
            await publisher.publish_payload(payload, tmp_path / "out.docx")

    def test_properties(self):
        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher
        publisher = DOCXPublisher()
        assert publisher.plugin_id == "docx"
        assert publisher.output_extension == ".docx"


# --- HTML Publisher Tests ---


class TestHTMLPublisher:
    """Tests for HTMLPublisher (mocking pypandoc)."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    async def test_publish_payload_produces_html(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.html_publisher import HTMLPublisher

        publisher = HTMLPublisher()
        payload = self._make_payload()

        mock_convert = MagicMock(return_value="<h1>Test Report</h1><p>Body content</p>")
        with patch.dict("sys.modules", {"pypandoc": MagicMock(convert_text=mock_convert)}):
            result = await publisher.publish_payload(payload, tmp_path / "out.html")

        assert result.exists()
        text = result.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text or "<html" in text
        assert "Test Report" in text

    async def test_uses_jinja2_template(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.html_publisher import HTMLPublisher

        publisher = HTMLPublisher()
        payload = self._make_payload(metadata={"date": "2026-02-20"})

        mock_convert = MagicMock(return_value="<p>Body</p>")
        with patch.dict("sys.modules", {"pypandoc": MagicMock(convert_text=mock_convert)}):
            result = await publisher.publish_payload(payload, tmp_path / "out.html")

        text = result.read_text(encoding="utf-8")
        # Should contain metadata and styled template elements
        assert "<title>" in text

    async def test_custom_template_path(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.html_publisher import HTMLPublisher

        # Create a custom template
        custom_tpl = tmp_path / "custom.html"
        custom_tpl.write_text(
            "<html><head><title>{{ title }}</title></head>"
            "<body><div class='custom'>{{ body }}</div></body></html>",
            encoding="utf-8",
        )

        publisher = HTMLPublisher()
        payload = self._make_payload()

        mock_convert = MagicMock(return_value="<p>Content</p>")
        with patch.dict("sys.modules", {"pypandoc": MagicMock(convert_text=mock_convert)}):
            result = await publisher.publish_payload(
                payload, tmp_path / "out.html",
                config={"template": str(custom_tpl)},
            )

        text = result.read_text(encoding="utf-8")
        assert "custom" in text

    def test_properties(self):
        from hiveflow.plugins.publishers.html_publisher import HTMLPublisher
        publisher = HTMLPublisher()
        assert publisher.plugin_id == "html"
        assert publisher.output_extension == ".html"


# --- Multi-Format Publish Tests ---


class TestMultiFormatPublish:
    """Integration tests for PublisherRegistry.publish_all with ResultPayload."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    async def test_publish_two_formats(self, tmp_path):
        """Publishing to markdown + json produces 2 files."""
        from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry
        from hiveflow.plugins.publishers.json_publisher import JSONPublisher

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(MarkdownPublisher())
        registry.register(JSONPublisher())

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), ["markdown", "json"], filename="report",
        )
        assert len(paths) == 2
        extensions = {p.suffix for p in paths}
        assert ".md" in extensions
        assert ".json" in extensions

    async def test_duplicate_format_deduplication(self, tmp_path):
        """Duplicate format names produce only one file."""
        from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(MarkdownPublisher())

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), ["markdown", "markdown"], filename="report",
        )
        assert len(paths) == 1

    async def test_missing_publisher_warning(self, tmp_path):
        """Missing publisher logs warning but doesn't block others."""
        from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(MarkdownPublisher())

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), ["markdown", "nonexistent"], filename="report",
        )
        assert len(paths) == 1  # markdown succeeds, nonexistent skipped

    async def test_one_failure_doesnt_block_others(self, tmp_path):
        """Error in one publisher doesn't prevent others."""
        from unittest.mock import AsyncMock

        from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry
        from hiveflow.plugins.publishers.json_publisher import JSONPublisher

        registry = PublisherRegistry(drop_in_dir=None)
        md = MarkdownPublisher()
        js = JSONPublisher()

        # Make JSON publisher fail
        js.publish_payload = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        registry.register(md)
        registry.register(js)

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), ["markdown", "json"], filename="report",
        )
        assert len(paths) == 1  # markdown succeeds despite json failure
        assert paths[0].suffix == ".md"

    async def test_legacy_string_api_still_works(self, tmp_path):
        """Passing a plain string still works (backward compat)."""
        from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(MarkdownPublisher())

        paths = await registry.publish_all(
            "# Hello\nWorld", str(tmp_path), ["markdown"], filename="legacy",
        )
        assert len(paths) == 1
        assert "Hello" in paths[0].read_text(encoding="utf-8")


# --- Third-Party Publisher Extensibility Tests (T039) ---


class TestThirdPartyPublisherExtensibility:
    """Integration tests for third-party publisher discovery and invocation."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    def test_mock_publisher_appears_in_registry(self):
        """A manually registered mock publisher appears in registry.list_ids()."""
        from hiveflow.plugins.publishers import PublisherPlugin, PublisherRegistry

        class LatexPublisher(PublisherPlugin):
            @property
            def plugin_id(self) -> str:
                return "latex"

            @property
            def description(self) -> str:
                return "Mock LaTeX publisher"

            @property
            def output_extension(self) -> str:
                return ".tex"

            async def publish(self, content, output_path, metadata=None):
                from pathlib import Path
                p = Path(output_path)
                if not p.suffix:
                    p = p.with_suffix(".tex")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                return p

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(LatexPublisher())

        assert "latex" in registry
        assert "latex" in registry.list_ids()
        assert registry.get("latex").description == "Mock LaTeX publisher"

    async def test_mock_publisher_invoked_via_publish_all(self, tmp_path):
        """A registered mock publisher can be invoked through publish_all()."""
        from hiveflow.plugins.publishers import PublisherPlugin, PublisherRegistry

        class LatexPublisher(PublisherPlugin):
            @property
            def plugin_id(self) -> str:
                return "latex"

            @property
            def description(self) -> str:
                return "Mock LaTeX publisher"

            @property
            def output_extension(self) -> str:
                return ".tex"

            async def publish(self, content, output_path, metadata=None):
                from pathlib import Path
                p = Path(output_path)
                if not p.suffix:
                    p = p.with_suffix(".tex")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"\\documentclass{{article}}\n{content}", encoding="utf-8")
                return p

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(LatexPublisher())

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), ["latex"], filename="report",
        )
        assert len(paths) == 1
        assert paths[0].suffix == ".tex"
        text = paths[0].read_text(encoding="utf-8")
        assert "\\documentclass" in text

    async def test_custom_publisher_error_doesnt_affect_builtin(self, tmp_path):
        """Error in a custom publisher doesn't block built-in publishers."""
        from hiveflow.plugins.publishers import (
            MarkdownPublisher,
            PublisherPlugin,
            PublisherRegistry,
        )

        class BrokenPublisher(PublisherPlugin):
            @property
            def plugin_id(self) -> str:
                return "broken"

            @property
            def description(self) -> str:
                return "Always fails"

            @property
            def output_extension(self) -> str:
                return ".brk"

            async def publish(self, content, output_path, metadata=None):
                raise RuntimeError("I am broken")

            async def publish_payload(self, payload, output_path, layout=None, config=None):
                raise RuntimeError("I am broken")

        registry = PublisherRegistry(drop_in_dir=None)
        registry.register(MarkdownPublisher())
        registry.register(BrokenPublisher())

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), ["markdown", "broken"], filename="report",
        )
        # Markdown should succeed; broken should fail silently
        assert len(paths) == 1
        assert paths[0].suffix == ".md"

    def test_entry_point_discovery_registers_builtins(self):
        """Entry point discovery should find the built-in publishers."""
        from hiveflow.plugins.publishers import PublisherRegistry

        registry = PublisherRegistry(drop_in_dir=None)
        registry.discover()

        # At minimum, the built-in publishers should be found
        ids = registry.list_ids()
        assert "markdown" in ids or "json" in ids  # at least one built-in found

    def test_create_factory_discovers_all_publishers(self):
        """PublisherRegistry.create() should discover all installed publishers."""
        from hiveflow.plugins.publishers import PublisherRegistry

        registry = PublisherRegistry.create()

        ids = registry.list_ids()
        # MarkdownPublisher is always registered by create()
        assert "markdown" in ids
        # Entry-point publishers should also be discovered
        assert "json" in ids

    async def test_empty_formats_publishes_all_discovered(self, tmp_path):
        """When formats list is empty, publish_all with all discovered IDs."""
        from hiveflow.plugins.publishers import PublisherRegistry

        registry = PublisherRegistry.create()
        all_ids = registry.list_ids()

        payload = self._make_payload()
        paths = await registry.publish_all(
            payload, str(tmp_path), all_ids, filename="report",
        )
        # Should produce at least markdown + json (always available)
        extensions = {p.suffix for p in paths}
        assert ".md" in extensions
        assert ".json" in extensions


# --- Retriever Tests ---


class TestSearchResult:
    def test_to_dict(self):
        result = SearchResult(
            title="Test", url="https://example.com",
            content="Content", score=0.9,
        )
        d = result.to_dict()
        assert d["title"] == "Test"
        assert d["score"] == 0.9


class TestRetrieverRegistry:
    def test_empty_registry(self):
        registry = RetrieverRegistry(drop_in_dir=None)
        assert len(registry) == 0


# --- Scraper Tests ---


class TestScrapedContent:
    def test_to_dict(self):
        content = ScrapedContent(
            url="https://example.com", title="Test",
            text="Hello world content",
        )
        d = content.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Test"

    def test_word_count(self):
        content = ScrapedContent(url="", title="", text="one two three four")
        assert content.word_count == 4


# --- Document Loader Tests ---


class TestDocument:
    def test_to_dict(self):
        doc = Document(content="Hello", source="test.txt")
        d = doc.to_dict()
        assert d["content"] == "Hello"
        assert d["source"] == "test.txt"

    def test_word_count(self):
        doc = Document(content="one two three", source="test.txt")
        assert doc.word_count == 3


class TestPlainTextLoader:
    async def test_load_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")

        loader = PlainTextLoader()
        doc = await loader.load(test_file)
        assert doc.content == "Hello, World!"
        assert doc.metadata["filename"] == "test.txt"

    def test_supported_extensions(self):
        loader = PlainTextLoader()
        assert ".txt" in loader.supported_extensions
        assert ".csv" in loader.supported_extensions


class TestChunkText:
    def test_short_text_no_chunking(self):
        chunks = chunk_text("short text", chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_chunks_with_overlap(self):
        text = " ".join(f"word{i}" for i in range(20))
        chunks = chunk_text(text, chunk_size=10, chunk_overlap=3)
        assert len(chunks) >= 2
        # Each chunk should have roughly 10 words
        for chunk in chunks:
            assert len(chunk.split()) <= 10

    def test_chunk_size_respected(self):
        text = " ".join(f"w{i}" for i in range(100))
        chunks = chunk_text(text, chunk_size=25, chunk_overlap=5)
        for chunk in chunks:
            assert len(chunk.split()) <= 25


# --- Layout-Aware Publisher Integration Tests ---


class TestLayoutAwareAssembly:
    """Tests that pandoc publishers use layout.apply() when layout is provided."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import PayloadSection, ResultPayload

        defaults = {
            "title": "Test Report",
            "content": "Main body content.",
            "sections": [
                PayloadSection(
                    section_id="sec_a",
                    title="Section A",
                    content="Content of A.",
                    order=2,
                ),
                PayloadSection(
                    section_id="sec_b",
                    title="Section B",
                    content="Content of B.",
                    order=1,
                ),
            ],
        }
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    def _make_layout(self):
        from hiveflow.core.layout import LayoutSection, LayoutTemplate

        return LayoutTemplate(
            name="test-layout",
            sections=[
                LayoutSection(id="title", source="title", required=True, heading=None),
                LayoutSection(id="body", source="content", required=True, heading="Body"),
                LayoutSection(
                    id="refs", source="references", required=False, heading="References"
                ),
            ],
        )

    def test_assemble_markdown_without_layout_uses_hardcoded_order(self):
        from hiveflow.plugins.publishers import PublisherPlugin

        payload = self._make_payload()
        md = PublisherPlugin.assemble_markdown(payload)
        assert "# Test Report" in md
        assert "Section A" in md
        assert "Section B" in md
        # Without layout, sections sorted by order: B (1) before A (2)
        pos_b = md.index("Section B")
        pos_a = md.index("Section A")
        assert pos_b < pos_a

    def test_assemble_markdown_with_layout_uses_apply(self):
        from hiveflow.plugins.publishers import PublisherPlugin

        payload = self._make_payload()
        layout = self._make_layout()
        md = PublisherPlugin.assemble_markdown(payload, layout)
        assert "# Test Report" in md
        assert "## Body" in md
        assert "Main body content." in md

    async def test_pdf_publish_payload_with_layout(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.pdf_publisher import PDFPublisher

        publisher = PDFPublisher()
        payload = self._make_payload()
        layout = self._make_layout()

        mock_convert = MagicMock()
        with patch.dict("sys.modules", {"pypandoc": MagicMock(convert_text=mock_convert)}):
            await publisher.publish_payload(
                payload, tmp_path / "out.pdf", layout=layout
            )

        md_content = mock_convert.call_args[0][0]
        assert "## Body" in md_content

    async def test_docx_publish_payload_with_layout(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher

        publisher = DOCXPublisher()
        payload = self._make_payload()
        layout = self._make_layout()

        mock_convert = MagicMock()
        with patch.dict("sys.modules", {"pypandoc": MagicMock(convert_text=mock_convert)}):
            await publisher.publish_payload(
                payload, tmp_path / "out.docx", layout=layout
            )

        md_content = mock_convert.call_args[0][0]
        assert "## Body" in md_content

    async def test_html_publish_payload_with_layout(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from hiveflow.plugins.publishers.html_publisher import HTMLPublisher

        publisher = HTMLPublisher()
        payload = self._make_payload()
        layout = self._make_layout()

        mock_pypandoc = MagicMock()
        mock_pypandoc.convert_text = MagicMock(return_value="<p>test</p>")
        mock_jinja2 = MagicMock()
        mock_template = MagicMock()
        mock_template.render.return_value = "<html>test</html>"
        mock_env = MagicMock()
        mock_env.from_string.return_value = mock_template
        mock_jinja2.Environment.return_value = mock_env

        with (
            patch.dict("sys.modules", {"pypandoc": mock_pypandoc, "jinja2": mock_jinja2}),
        ):
            await publisher.publish_payload(
                payload, tmp_path / "out.html", layout=layout
            )

        md_content = mock_pypandoc.convert_text.call_args[0][0]
        assert "## Body" in md_content
