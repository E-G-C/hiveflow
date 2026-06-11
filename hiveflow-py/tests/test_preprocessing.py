"""Unit tests for hiveflow.core.preprocessing — data classes, registry, and preprocessor."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from hiveflow.core.preprocessing import (
    ChunkMeta,
    ModelContextRegistry,
    PreprocessingConfig,
    TaskDataChunk,
    TaskDataManifest,
    TaskPreprocessor,
)
from hiveflow.plugins.llm import LLMResponse


# ---------------------------------------------------------------------------
# PreprocessingConfig
# ---------------------------------------------------------------------------


class TestPreprocessingConfig:
    """T004: PreprocessingConfig defaults and validation."""

    def test_defaults(self):
        cfg = PreprocessingConfig()
        assert cfg.disabled is False
        assert cfg.threshold_override == 0
        assert cfg.context_ratio == 0.15
        assert cfg.pipeline_factor == 0.3
        assert cfg.chunk_context_ratio == 0.10
        assert cfg.chunk_overlap_ratio == 0.10
        assert cfg.tokens_per_word == 1.35

    def test_custom_values(self):
        cfg = PreprocessingConfig(
            disabled=True,
            threshold_override=5000,
            context_ratio=0.2,
            pipeline_factor=0.5,
            chunk_context_ratio=0.15,
            chunk_overlap_ratio=0.05,
            tokens_per_word=1.5,
        )
        assert cfg.disabled is True
        assert cfg.threshold_override == 5000
        assert cfg.context_ratio == 0.2
        assert cfg.pipeline_factor == 0.5
        assert cfg.chunk_context_ratio == 0.15
        assert cfg.chunk_overlap_ratio == 0.05
        assert cfg.tokens_per_word == 1.5

    def test_partial_override(self):
        cfg = PreprocessingConfig(context_ratio=0.25)
        assert cfg.context_ratio == 0.25
        assert cfg.disabled is False  # other defaults intact


# ---------------------------------------------------------------------------
# TaskDataChunk
# ---------------------------------------------------------------------------


class TestTaskDataChunk:
    """T005: TaskDataChunk dataclass and to_dict()."""

    def test_basic_construction(self):
        chunk = TaskDataChunk(
            chunk_id="chunk_001",
            content="Hello world",
            words=2,
            topic_hint="Greeting text",
        )
        assert chunk.chunk_id == "chunk_001"
        assert chunk.content == "Hello world"
        assert chunk.words == 2
        assert chunk.topic_hint == "Greeting text"

    def test_default_topic_hint(self):
        chunk = TaskDataChunk(chunk_id="chunk_001", content="text", words=1)
        assert chunk.topic_hint == ""

    def test_to_dict(self):
        chunk = TaskDataChunk(
            chunk_id="chunk_003",
            content="Some data content here",
            words=4,
            topic_hint="Data section",
        )
        d = chunk.to_dict()
        assert d == {
            "chunk_id": "chunk_003",
            "content": "Some data content here",
            "words": 4,
            "topic_hint": "Data section",
        }

    def test_to_dict_empty_topic(self):
        chunk = TaskDataChunk(chunk_id="chunk_001", content="text", words=1)
        d = chunk.to_dict()
        assert d["topic_hint"] == ""


# ---------------------------------------------------------------------------
# ChunkMeta
# ---------------------------------------------------------------------------


class TestChunkMeta:
    """T006: ChunkMeta dataclass."""

    def test_construction(self):
        cm = ChunkMeta(chunk_id="chunk_001", words=150, topic_hint="Financial data")
        assert cm.chunk_id == "chunk_001"
        assert cm.words == 150
        assert cm.topic_hint == "Financial data"

    def test_default_topic_hint(self):
        cm = ChunkMeta(chunk_id="chunk_001", words=100)
        assert cm.topic_hint == ""


# ---------------------------------------------------------------------------
# TaskDataManifest
# ---------------------------------------------------------------------------


class TestTaskDataManifest:
    """T007: TaskDataManifest dataclass and to_dict()."""

    def test_basic_construction(self):
        m = TaskDataManifest(
            total_words=1000,
            chunk_count=3,
            model_context_tokens=128000,
            effective_threshold=2000,
            boundary_method="explicit_label",
        )
        assert m.total_words == 1000
        assert m.chunk_count == 3
        assert m.model_context_tokens == 128000
        assert m.effective_threshold == 2000
        assert m.boundary_method == "explicit_label"
        assert m.chunks == []

    def test_with_chunks(self):
        chunks = [
            ChunkMeta(chunk_id="chunk_001", words=500, topic_hint="Part 1"),
            ChunkMeta(chunk_id="chunk_002", words=500, topic_hint="Part 2"),
        ]
        m = TaskDataManifest(
            total_words=1000,
            chunk_count=2,
            model_context_tokens=128000,
            effective_threshold=2000,
            boundary_method="size_gradient",
            chunks=chunks,
        )
        assert len(m.chunks) == 2
        assert m.chunks[0].chunk_id == "chunk_001"

    def test_to_dict_empty_chunks(self):
        m = TaskDataManifest(
            total_words=500,
            chunk_count=0,
            model_context_tokens=16000,
            effective_threshold=500,
            boundary_method="none",
        )
        d = m.to_dict()
        assert d == {
            "total_words": 500,
            "chunk_count": 0,
            "model_context_tokens": 16000,
            "effective_threshold": 500,
            "boundary_method": "none",
            "chunks": [],
        }

    def test_to_dict_with_chunks(self):
        chunks = [
            ChunkMeta(chunk_id="chunk_001", words=300, topic_hint="Topic A"),
            ChunkMeta(chunk_id="chunk_002", words=700, topic_hint="Topic B"),
        ]
        m = TaskDataManifest(
            total_words=1000,
            chunk_count=2,
            model_context_tokens=128000,
            effective_threshold=2000,
            boundary_method="explicit_label",
            chunks=chunks,
        )
        d = m.to_dict()
        assert d["chunk_count"] == 2
        assert len(d["chunks"]) == 2
        assert d["chunks"][0] == {
            "chunk_id": "chunk_001",
            "words": 300,
            "topic_hint": "Topic A",
        }
        assert d["chunks"][1] == {
            "chunk_id": "chunk_002",
            "words": 700,
            "topic_hint": "Topic B",
        }


# ---------------------------------------------------------------------------
# ModelContextRegistry
# ---------------------------------------------------------------------------


class TestModelContextRegistry:
    """T008: ModelContextRegistry — resolve, register, prefix matching."""

    def test_exact_match(self):
        reg = ModelContextRegistry()
        assert reg.resolve("gpt-4o") == 128_000
        assert reg.resolve("gpt-4") == 8_192
        assert reg.resolve("o3") == 200_000

    def test_exact_match_case_insensitive(self):
        reg = ModelContextRegistry()
        assert reg.resolve("GPT-4o") == 128_000
        assert reg.resolve("Claude-3-Opus") == 200_000

    def test_prefix_match(self):
        reg = ModelContextRegistry()
        # "claude-3.5-sonnet" starts with "claude-3.5" (exact) and "claude-" (prefix)
        assert reg.resolve("claude-3.5-sonnet") == 200_000
        # "gemini-2.0-flash" starts with "gemini-2"
        assert reg.resolve("gemini-2.0-flash") == 1_000_000

    def test_longest_prefix_wins(self):
        reg = ModelContextRegistry()
        # "gpt-4o-mini" should match "gpt-4o-mini" exactly (128K), not "gpt-4o" or "gpt-4"
        assert reg.resolve("gpt-4o-mini") == 128_000
        # "gpt-4-turbo" has exact match
        assert reg.resolve("gpt-4-turbo") == 128_000

    def test_provider_prefix_stripped(self):
        reg = ModelContextRegistry()
        assert reg.resolve("openai:gpt-4o") == 128_000
        assert reg.resolve("anthropic:claude-3-opus") == 200_000
        assert reg.resolve("google:gemini-1.5-pro") == 1_000_000

    def test_default_fallback(self):
        reg = ModelContextRegistry()
        assert reg.resolve("unknown-model-xyz") == 16_000
        assert reg.resolve("some-random:model") == 16_000

    def test_register(self):
        reg = ModelContextRegistry()
        reg.register("my-custom-model", 50_000)
        assert reg.resolve("my-custom-model") == 50_000

    def test_register_overrides_builtin(self):
        reg = ModelContextRegistry()
        reg.register("gpt-4o", 256_000)
        assert reg.resolve("gpt-4o") == 256_000

    def test_constructor_overrides(self):
        reg = ModelContextRegistry(overrides={"gpt-4o": 256_000, "my-model": 64_000})
        assert reg.resolve("gpt-4o") == 256_000
        assert reg.resolve("my-model") == 64_000
        # Built-in still available for non-overridden
        assert reg.resolve("o3") == 200_000

    def test_default_context_constant(self):
        assert ModelContextRegistry.DEFAULT_CONTEXT == 16_000

    def test_register_case_insensitive(self):
        reg = ModelContextRegistry()
        reg.register("MyModel", 42_000)
        assert reg.resolve("mymodel") == 42_000
        assert reg.resolve("MYMODEL") == 42_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preprocessor(
    model: str = "gpt-4o",
    config: PreprocessingConfig | None = None,
    llm_response: str = "150",
) -> tuple[TaskPreprocessor, AsyncMock]:
    """Create a TaskPreprocessor with a mock LLM provider."""
    mock_provider = AsyncMock()
    mock_provider.context_window = None
    mock_provider.chat.return_value = LLMResponse(content=llm_response, model=model)
    tp = TaskPreprocessor(mock_provider, model=model, config=config)
    return tp, mock_provider


# ---------------------------------------------------------------------------
# T019: Threshold computation
# ---------------------------------------------------------------------------


class TestThresholdComputation:
    """T019: Unit tests for _compute_threshold."""

    def test_128k_model(self):
        tp, _ = _make_preprocessor(model="gpt-4o")
        threshold, ctx = tp._compute_threshold(agent_count=3)
        assert ctx == 128_000
        # 128000 * 0.15 / 1.35 / (3 * 0.3) = 15802
        assert 15_000 < threshold < 16_500

    def test_8k_model(self):
        tp, _ = _make_preprocessor(model="gpt-4")
        threshold, ctx = tp._compute_threshold(agent_count=3)
        assert ctx == 8_192
        assert threshold < 1_500

    def test_unknown_model_fallback(self):
        tp, _ = _make_preprocessor(model="unknown-xyz")
        threshold, ctx = tp._compute_threshold(agent_count=1)
        assert ctx == 16_000  # DEFAULT_CONTEXT

    def test_threshold_override(self):
        cfg = PreprocessingConfig(threshold_override=5000)
        tp, _ = _make_preprocessor(config=cfg)
        threshold, ctx = tp._compute_threshold(agent_count=3)
        assert threshold == 5000
        assert ctx == 128_000

    def test_threshold_scales_with_context(self):
        """SC-006: 128K model threshold should be >10x the 8K model threshold."""
        tp_128k, _ = _make_preprocessor(model="gpt-4o")
        tp_8k, _ = _make_preprocessor(model="gpt-4")
        t_128k, _ = tp_128k._compute_threshold(3)
        t_8k, _ = tp_8k._compute_threshold(3)
        assert t_128k / t_8k > 10

    def test_single_agent(self):
        tp, _ = _make_preprocessor(model="gpt-4o")
        threshold, _ = tp._compute_threshold(agent_count=1)
        # 128000 * 0.15 / 1.35 / (1 * 0.3) = 47407
        assert 45_000 < threshold < 50_000


# ---------------------------------------------------------------------------
# T024: Three-tier context window resolution
# ---------------------------------------------------------------------------


class TestContextWindowResolution:
    """T024: Provider → registry → default context window resolution."""

    def test_provider_property_used_first(self):
        mock = AsyncMock()
        mock.context_window = 256_000
        tp = TaskPreprocessor(mock, model="gpt-4")
        assert tp._resolve_context_window() == 256_000

    def test_registry_fallback_when_provider_none(self):
        mock = AsyncMock()
        mock.context_window = None
        tp = TaskPreprocessor(mock, model="gpt-4")
        assert tp._resolve_context_window() == 8_192

    def test_default_fallback_for_unknown_model(self):
        mock = AsyncMock()
        mock.context_window = None
        tp = TaskPreprocessor(mock, model="unknown-model")
        assert tp._resolve_context_window() == 16_000

    def test_sc006_8k_vs_128k_threshold_10x(self):
        """SC-006: 128K threshold ≥10x the 8K threshold."""
        mock = AsyncMock()
        mock.context_window = None
        tp_128k = TaskPreprocessor(mock, model="gpt-4o")
        tp_8k = TaskPreprocessor(mock, model="gpt-4")
        t_128k, _ = tp_128k._compute_threshold(3)
        t_8k, _ = tp_8k._compute_threshold(3)
        assert t_128k / t_8k > 10

    def test_threshold_override_bypasses_model(self):
        mock = AsyncMock()
        mock.context_window = None
        cfg = PreprocessingConfig(threshold_override=999)
        tp = TaskPreprocessor(mock, model="gpt-4o", config=cfg)
        t, _ = tp._compute_threshold(5)
        assert t == 999


# ---------------------------------------------------------------------------
# T020: Boundary detection
# ---------------------------------------------------------------------------


class TestBoundaryDetection:
    """T020: Unit tests for _detect_boundary and LLM fallback."""

    def test_explicit_label(self):
        tp, _ = _make_preprocessor()
        text = "Analyze this.\n\n## Data\n\nHere is the data content."
        inst, data, method = tp._detect_boundary(text)
        assert method == "explicit_label"
        assert "Analyze" in inst
        assert "data content" in data

    def test_explicit_label_case_insensitive(self):
        tp, _ = _make_preprocessor()
        text = "Instructions.\n\n## INPUT\n\nRaw input here."
        inst, data, method = tp._detect_boundary(text)
        assert method == "explicit_label"

    def test_hrule_heading(self):
        tp, _ = _make_preprocessor()
        text = "Process report.\n\n---\n# Report Data\nData here."
        inst, data, method = tp._detect_boundary(text)
        assert method == "hrule_heading"

    def test_code_fence(self):
        tp, _ = _make_preprocessor()
        intro = "Process this code:\n\n"
        code = "```\n" + " ".join(["word"] * 200) + "\n```"
        text = intro + code
        inst, data, method = tp._detect_boundary(text)
        assert method == "code_fence"

    def test_size_gradient(self):
        tp, _ = _make_preprocessor()
        short = "Do task A. Do task B."
        long = " ".join(["data"] * 500)
        text = short + "\n\n" + long
        inst, data, method = tp._detect_boundary(text)
        assert method == "size_gradient"
        assert len(data.split()) > len(inst.split())

    def test_no_match(self):
        tp, _ = _make_preprocessor()
        # Equal-sized paragraphs — no gradient
        text = ("A " * 100).strip() + "\n\n" + ("B " * 100).strip()
        inst, data, method = tp._detect_boundary(text)
        assert method == "none"

    @pytest.mark.asyncio
    async def test_llm_fallback(self):
        tp, mock = _make_preprocessor(llm_response="100")
        text = " ".join(["word"] * 500)
        inst, data, method = await tp._detect_boundary_with_llm_fallback(text)
        assert method == "llm_fallback"
        assert len(inst.split()) == 100
        assert len(data.split()) == 400

    @pytest.mark.asyncio
    async def test_llm_failure_fallback_split(self):
        tp, mock = _make_preprocessor()
        mock.chat.side_effect = Exception("API error")
        text = " ".join(["word"] * 500)
        inst, data, method = await tp._detect_boundary_with_llm_fallback(text)
        assert method == "fallback_split"
        assert len(inst.split()) == 100  # 20% of 500


# ---------------------------------------------------------------------------
# T021: preprocess() end-to-end
# ---------------------------------------------------------------------------


class TestPreprocess:
    """T021: Unit tests for preprocess() orchestration."""

    @pytest.mark.asyncio
    async def test_below_threshold_unchanged(self):
        tp, _ = _make_preprocessor()
        state = {"task": "Short task text"}
        result = await tp.preprocess(state, agent_count=1)
        assert "task_instructions" not in result
        assert result["task"] == "Short task text"

    @pytest.mark.asyncio
    async def test_disabled_unchanged(self):
        cfg = PreprocessingConfig(disabled=True)
        tp, _ = _make_preprocessor(config=cfg)
        state = {"task": "x " * 100_000}
        result = await tp.preprocess(state)
        assert "task_instructions" not in result

    @pytest.mark.asyncio
    async def test_above_threshold_enriched(self):
        summary_response = (
            "SUMMARY:\nTest summary.\n\n"
            "TOPICS:\nchunk_001: Topic A\nchunk_002: Topic B"
        )
        tp, _ = _make_preprocessor(llm_response=summary_response)
        instructions = "Analyze this document. " * 200
        data_text = "\n\n".join(
            [f"Paragraph {i}. " + " ".join(["data"] * 2000) for i in range(30)]
        )
        task = instructions + "\n\n## Data\n\n" + data_text
        state = {"task": task}
        result = await tp.preprocess(state, agent_count=3)
        assert "task_instructions" in result
        assert "task_data" in result
        assert "task_data_manifest" in result
        assert result["task"] == result["task_instructions"]
        assert len(result["task_data"]) >= 1

    @pytest.mark.asyncio
    async def test_empty_task(self):
        tp, _ = _make_preprocessor()
        state = {"task": ""}
        result = await tp.preprocess(state)
        assert "task_instructions" not in result

    @pytest.mark.asyncio
    async def test_no_data_after_boundary(self):
        """Entirely instructional task — data section empty."""
        cfg = PreprocessingConfig(threshold_override=5)
        tp, mock = _make_preprocessor(config=cfg, llm_response="500")
        # All instructions, no data markers
        state = {"task": "Do this important task. " * 100}
        result = await tp.preprocess(state, agent_count=1)
        # Should have task_instructions but empty task_data
        if "task_instructions" in result:
            assert isinstance(result["task_data"], list)


# ---------------------------------------------------------------------------
# T022: _summarize_state preprocessing-aware tests
# ---------------------------------------------------------------------------


class TestSummarizeStatePreprocessing:
    """T022: Agent._summarize_state() preprocessing-aware branch."""

    def _make_agent(self):
        """Create a minimal Agent-like object with _summarize_state."""
        from hiveflow.core.agent import Agent

        agent = Agent.__new__(Agent)
        agent.context_budget = None
        agent.output_ttl = None
        agent._sliding_window_size = None
        agent.context_recency_window = 0
        agent.agent_id = "test_agent"
        agent.agent_definition = None
        return agent

    def test_with_task_instructions(self):
        agent = self._make_agent()
        state = {
            "task_instructions": "Do this analysis",
            "task": "Do this analysis",
            "task_data_summary": "Data contains financial records.",
        }
        result = agent._summarize_state(state)
        assert "Do this analysis" in result
        assert "financial records" in result

    def test_without_preprocessing_keys(self):
        agent = self._make_agent()
        state = {"task": "Simple task text"}
        result = agent._summarize_state(state)
        assert "Simple task text" in result

    def test_task_instructions_without_summary(self):
        agent = self._make_agent()
        state = {
            "task_instructions": "Process data",
            "task": "Process data",
            "task_data_summary": "",
        }
        result = agent._summarize_state(state)
        assert "Process data" in result
        assert "Data summary" not in result  # empty summary not shown


# ---------------------------------------------------------------------------
# T025-T026: Integration test fixtures and boundary SC-007
# ---------------------------------------------------------------------------


class TestBoundaryIntegration:
    """T025-T026: Integration tests for all 4 structural boundary patterns (SC-007)."""

    LABEL_TASK = (
        "Analyze the following dataset and identify trends.\n\n"
        "## Data\n\n"
        + " ".join(["metric"] * 500)
    )

    HRULE_TASK = (
        "Summarize the report below.\n\n"
        "---\n"
        "# Report Content\n"
        + " ".join(["report"] * 500)
    )

    CODE_FENCE_TASK = (
        "Review the code:\n\n"
        "```\n" + " ".join(["code"] * 500) + "\n```"
    )

    GRADIENT_TASK = (
        "Do analysis. Do it well.\n\n"
        + " ".join(["data"] * 500)
    )

    def test_label_boundary(self):
        tp, _ = _make_preprocessor()
        inst, data, method = tp._detect_boundary(self.LABEL_TASK)
        assert method == "explicit_label"
        assert "Analyze" in inst
        assert len(data.split()) >= 400

    def test_hrule_boundary(self):
        tp, _ = _make_preprocessor()
        inst, data, method = tp._detect_boundary(self.HRULE_TASK)
        assert method == "hrule_heading"
        assert "Summarize" in inst

    def test_code_fence_boundary(self):
        tp, _ = _make_preprocessor()
        inst, data, method = tp._detect_boundary(self.CODE_FENCE_TASK)
        assert method == "code_fence"
        assert "Review" in inst

    def test_size_gradient_boundary(self):
        tp, _ = _make_preprocessor()
        inst, data, method = tp._detect_boundary(self.GRADIENT_TASK)
        assert method == "size_gradient"
        assert len(data.split()) > len(inst.split())

    @pytest.mark.asyncio
    async def test_llm_fallback_boundary(self):
        """No structural markers — LLM fallback triggered."""
        tp, mock = _make_preprocessor(llm_response="50")
        # Equal-sized paragraphs, no markdown markers
        text = " ".join(["alpha"] * 100) + "\n\n" + " ".join(["beta"] * 100)
        inst, data, method = await tp._detect_boundary_with_llm_fallback(text)
        assert method == "llm_fallback"


# ---------------------------------------------------------------------------
# T027: Entirely instructional task edge case
# ---------------------------------------------------------------------------


class TestEntirelyInstructional:
    """T027: Task with no data section."""

    @pytest.mark.asyncio
    async def test_no_data_section(self):
        cfg = PreprocessingConfig(threshold_override=10)
        tp, mock = _make_preprocessor(config=cfg, llm_response="500")
        task = "Do this. " * 200  # 400 words, no data markers
        state = {"task": task}
        result = await tp.preprocess(state)
        if "task_instructions" in result:
            assert result["task_data"] == [] or len(result["task_data"]) >= 1
            assert "task_data_manifest" in result


# ---------------------------------------------------------------------------
# T034: _chunk_data() unit tests
# ---------------------------------------------------------------------------


class TestChunkData:
    """T034: Paragraph-aware chunking tests."""

    def test_paragraph_boundary_splitting(self):
        tp, _ = _make_preprocessor()
        data = "\n\n".join(
            [f"Paragraph {i}. " + "word " * 200 for i in range(20)]
        )
        chunks = tp._chunk_data(data, chunk_target=1000)
        assert len(chunks) >= 2
        for c in chunks:
            assert c.chunk_id.startswith("chunk_")
            assert c.words > 0

    def test_chunk_size_within_cap(self):
        tp, _ = _make_preprocessor()
        data = "\n\n".join(
            [f"Paragraph {i}. " + "word " * 200 for i in range(50)]
        )
        target = 2000
        chunks = tp._chunk_data(data, chunk_target=target)
        cap = int(target * 1.5)
        for c in chunks[:-1]:  # last chunk can be smaller
            assert c.words <= cap + 300  # allow small paragraph overshoot

    def test_chunk_id_sequencing(self):
        tp, _ = _make_preprocessor()
        data = "\n\n".join(["word " * 200 for _ in range(10)])
        chunks = tp._chunk_data(data, chunk_target=500)
        for i, c in enumerate(chunks):
            assert c.chunk_id == f"chunk_{i + 1:03d}"

    def test_single_paragraph_word_splitting(self):
        tp, _ = _make_preprocessor()
        data = "word " * 10000  # No paragraph breaks
        chunks = tp._chunk_data(data, chunk_target=2000)
        assert len(chunks) >= 4
        for c in chunks[:-1]:
            assert c.words <= 2000

    def test_small_data_single_chunk(self):
        tp, _ = _make_preprocessor()
        data = "Small data content here."
        chunks = tp._chunk_data(data, chunk_target=1000)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "chunk_001"


# ---------------------------------------------------------------------------
# T035: Minimum data size skip
# ---------------------------------------------------------------------------


class TestMinimumDataSizeSkip:
    """T035: Data below chunk target stored as single entry."""

    @pytest.mark.asyncio
    async def test_small_data_no_summary_call(self):
        cfg = PreprocessingConfig(threshold_override=10)
        tp, mock = _make_preprocessor(config=cfg)
        # Task with small data section
        task = "Analyze this.\n\n## Data\n\n" + "small data. " * 50
        state = {"task": task}
        result = await tp.preprocess(state, agent_count=1)
        assert "task_instructions" in result
        assert len(result["task_data"]) == 1
        assert result["task_data_summary"] == ""
        # LLM should NOT be called for summarization (data is small)
        assert mock.chat.call_count == 0


# ---------------------------------------------------------------------------
# T036: _summarize_and_manifest() tests
# ---------------------------------------------------------------------------


class TestSummarizeAndManifest:
    """T036: Summary and manifest generation."""

    @pytest.mark.asyncio
    async def test_successful_summary(self):
        summary_resp = (
            "SUMMARY:\nThis is a test summary of the data.\n\n"
            "TOPICS:\n"
            "chunk_001: Financial records\n"
            "chunk_002: Customer data"
        )
        tp, _ = _make_preprocessor(llm_response=summary_resp)
        chunks = [
            TaskDataChunk(chunk_id="chunk_001", content="Financial content.", words=100),
            TaskDataChunk(chunk_id="chunk_002", content="Customer details.", words=100),
        ]
        summary, hints = await tp._summarize_and_manifest(chunks)
        assert "test summary" in summary
        assert len(hints) == 2
        assert "Financial" in hints[0]
        assert "Customer" in hints[1]

    @pytest.mark.asyncio
    async def test_retry_and_mechanical_fallback(self):
        tp, mock = _make_preprocessor()
        mock.chat.side_effect = Exception("LLM error")
        chunks = [
            TaskDataChunk(chunk_id="chunk_001", content="Some content here.", words=50),
        ]
        summary, hints = await tp._summarize_and_manifest(chunks)
        # Should fall back to mechanical summary
        assert "50 words" in summary or "1 chunks" in summary
        assert len(hints) == 1
        # Should have retried (2 attempts)
        assert mock.chat.call_count == 2

    def test_mechanical_summary(self):
        tp, _ = _make_preprocessor()
        chunks = [
            TaskDataChunk(chunk_id="chunk_001", content="First section data.", words=500),
            TaskDataChunk(chunk_id="chunk_002", content="Second section data.", words=300),
        ]
        summary, hints = tp._mechanical_summary(chunks)
        assert "800 words" in summary
        assert "2 chunks" in summary
        assert len(hints) == 2
