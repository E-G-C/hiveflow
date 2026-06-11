"""Task preprocessing for large-input context management.

Automatically detects when a task input exceeds a model-derived threshold,
separates instructions from data, chunks the data into model-appropriate
segments, and generates a compact summary and manifest for routing agents.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class PreprocessingConfig(BaseModel):
    """Configuration for task preprocessing parameters."""

    disabled: bool = False
    threshold_override: int = 0  # 0 = auto-compute from model
    context_ratio: float = 0.15  # Fraction of context window for threshold
    pipeline_factor: float = 0.3  # Per-agent context multiplier
    chunk_context_ratio: float = 0.10  # Fraction of context window per chunk
    chunk_overlap_ratio: float = 0.10  # Overlap as fraction of chunk size
    tokens_per_word: float = 1.35  # Token-to-word conversion ratio


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TaskDataChunk:
    """A segment of the data section."""

    chunk_id: str  # e.g., "chunk_001"
    content: str  # The chunk text
    words: int  # Word count
    topic_hint: str = ""  # One-sentence topic description

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for state storage."""
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "words": self.words,
            "topic_hint": self.topic_hint,
        }


@dataclass
class ChunkMeta:
    """Per-chunk entry in the manifest."""

    chunk_id: str
    words: int
    topic_hint: str = ""


@dataclass
class TaskDataManifest:
    """Metadata describing all chunks."""

    total_words: int
    chunk_count: int
    model_context_tokens: int
    effective_threshold: int
    boundary_method: str
    chunks: list[ChunkMeta] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for state storage."""
        return {
            "total_words": self.total_words,
            "chunk_count": self.chunk_count,
            "model_context_tokens": self.model_context_tokens,
            "effective_threshold": self.effective_threshold,
            "boundary_method": self.boundary_method,
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "words": c.words,
                    "topic_hint": c.topic_hint,
                }
                for c in self.chunks
            ],
        }


# ---------------------------------------------------------------------------
# Model context registry
# ---------------------------------------------------------------------------

# Built-in model context window sizes (tokens).
_BUILT_IN_MODELS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5": 16_385,
    "o3-mini": 128_000,
    "o3": 200_000,
    "o1": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5": 200_000,
    "claude-": 200_000,
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2": 1_000_000,
    "mistral-large": 128_000,
    "mistral-medium": 32_000,
    "mistral-small": 32_000,
    "command-r-plus": 128_000,
    "command-r": 128_000,
}


class ModelContextRegistry:
    """Maps model name prefixes to context window sizes in tokens.

    Resolution order:
    1. Exact match
    2. Longest prefix match
    3. ``DEFAULT_CONTEXT`` fallback (16,000)
    """

    DEFAULT_CONTEXT: int = 16_000

    def __init__(self, overrides: dict[str, int] | None = None) -> None:
        self._registry: dict[str, int] = dict(_BUILT_IN_MODELS)
        if overrides:
            self._registry.update(overrides)

    def resolve(self, model: str) -> int:
        """Return the context window in tokens for *model*.

        Strips a leading ``provider:`` prefix (e.g. ``openai:gpt-4o`` →
        ``gpt-4o``) before matching.
        """
        # Strip provider prefix
        bare = model.split(":", 1)[-1] if ":" in model else model
        bare_lower = bare.lower()

        # 1. Exact match
        if bare_lower in self._registry:
            return self._registry[bare_lower]

        # 2. Longest prefix match
        best_prefix = ""
        best_tokens = 0
        for prefix, tokens in self._registry.items():
            if bare_lower.startswith(prefix) and len(prefix) > len(best_prefix):
                best_prefix = prefix
                best_tokens = tokens
        if best_prefix:
            return best_tokens

        # 3. Default fallback
        return self.DEFAULT_CONTEXT

    def register(self, prefix: str, context_tokens: int) -> None:
        """Add or update a model prefix entry at runtime."""
        self._registry[prefix.lower()] = context_tokens


# ---------------------------------------------------------------------------
# Boundary detection patterns
# ---------------------------------------------------------------------------

# Explicit section labels (case-insensitive)
_DATA_SECTION_RE = re.compile(
    r"^##?\s+(Data|Content|Input|Source)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Horizontal rule followed by a heading within 2 lines
_HRULE_HEADING_RE = re.compile(
    r"^(?:---+|\*\*\*+)\s*\n(?:\s*\n)?(?:#)",
    re.MULTILINE,
)

# Fenced code block (opening)
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)


# ---------------------------------------------------------------------------
# Task preprocessor
# ---------------------------------------------------------------------------


class TaskPreprocessor:
    """Pre-execution pipeline for separating, chunking, and summarizing
    large task inputs."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        model: str = "",
        config: PreprocessingConfig | None = None,
        context_registry: ModelContextRegistry | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._model = model.split(":", 1)[-1] if ":" in model else model
        self._model_full = model
        self._config = config or PreprocessingConfig()
        self._registry = context_registry or ModelContextRegistry()

    # -- Threshold computation (T011) -----------------------------------------

    def _resolve_context_window(self) -> int:
        """Resolve the model context window in tokens.

        Resolution order:
        1. Provider ``context_window`` property (if not None)
        2. ``ModelContextRegistry`` lookup
        """
        provider_ctx = getattr(self._llm_provider, "context_window", None)
        if provider_ctx is not None:
            return provider_ctx
        return self._registry.resolve(self._model_full)

    def _compute_threshold(self, agent_count: int = 1) -> tuple[int, int]:
        """Compute the word-count threshold for preprocessing activation.

        Returns:
            ``(threshold_words, context_window_tokens)``
        """
        if self._config.threshold_override > 0:
            ctx = self._resolve_context_window()
            return self._config.threshold_override, ctx

        ctx = self._resolve_context_window()
        effective_agents = max(agent_count, 1) * self._config.pipeline_factor
        threshold = int(
            ctx * self._config.context_ratio / self._config.tokens_per_word / effective_agents
        )
        return max(threshold, 1), ctx

    # -- Boundary detection (T012 + T013) -------------------------------------

    def _detect_boundary(self, text: str) -> tuple[str, str, str]:
        """Separate *text* into (instructions, data, method).

        Heuristic cascade (R8):
        1. Explicit section labels (``## Data``, ``## Content``, etc.)
        2. Horizontal rule + heading
        3. Fenced code block enclosing >60% of words
        4. Size gradient (short <30% → long >70%)
        5. Returned ``("", "", "none")`` — caller decides fallback
        """
        # 1. Explicit section labels
        m = _DATA_SECTION_RE.search(text)
        if m:
            return text[: m.start()].rstrip(), text[m.end() :].lstrip(), "explicit_label"

        # 2. Horizontal rule + heading
        m = _HRULE_HEADING_RE.search(text)
        if m:
            return text[: m.start()].rstrip(), text[m.start() :].lstrip(), "hrule_heading"

        # 3. Fenced code block enclosing >60% of total words
        fences = list(_CODE_FENCE_RE.finditer(text))
        total_words = len(text.split())
        if len(fences) >= 2:
            # Check consecutive pairs for large blocks
            for i in range(0, len(fences) - 1, 2):
                open_pos = fences[i].start()
                close_pos = fences[i + 1].end()
                block_text = text[open_pos:close_pos]
                if len(block_text.split()) > total_words * 0.6:
                    return (
                        text[:open_pos].rstrip(),
                        text[open_pos:].lstrip(),
                        "code_fence",
                    )

        # 4. Size gradient — find paragraph boundary splitting short/long
        paragraphs = re.split(r"\n\s*\n", text)
        if len(paragraphs) >= 2:
            cumulative = 0
            word_counts = [len(p.split()) for p in paragraphs]
            for idx in range(len(paragraphs) - 1):
                cumulative += word_counts[idx]
                remaining = total_words - cumulative
                if (
                    total_words > 0
                    and cumulative < total_words * 0.30
                    and remaining > total_words * 0.70
                ):
                    # Find the actual position in text after the paragraph
                    joined_before = "\n\n".join(paragraphs[: idx + 1])
                    joined_after = "\n\n".join(paragraphs[idx + 1 :])
                    return joined_before.rstrip(), joined_after.lstrip(), "size_gradient"

        # 5. No structural pattern found
        return "", "", "none"

    async def _detect_boundary_with_llm_fallback(self, text: str) -> tuple[str, str, str]:
        """Run heuristic boundary detection, falling back to LLM if needed."""
        instructions, data, method = self._detect_boundary(text)

        if method != "none":
            return instructions, data, method

        # LLM fallback: send first 2000 words and ask for boundary
        words = text.split()
        sample = " ".join(words[:2000])
        try:
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are analyzing a text document that contains both "
                        "instructions (what the user wants done) and data (the "
                        "content to process). Identify where the instructions end "
                        "and the data begins. Respond with ONLY the number of the "
                        "last word that is part of the instructions. For example, "
                        "if the first 150 words are instructions, respond with '150'."
                    ),
                ),
                LLMMessage(role="user", content=sample),
            ]
            config = LLMConfig(
                model=self._model,
                max_tokens=50,
                temperature=0.0,
            )
            response = await self._llm_provider.chat(messages, config)
            boundary_word = int(re.search(r"\d+", response.content).group())
            boundary_word = max(1, min(boundary_word, len(words)))
            instructions_text = " ".join(words[:boundary_word])
            data_text = " ".join(words[boundary_word:])
            return instructions_text, data_text, "llm_fallback"
        except Exception as exc:
            logger.warning(
                "task_preprocessing.llm_boundary_failed",
                error=str(exc),
            )
            # Conservative 20/80 split
            split_point = max(1, len(words) // 5)
            return (
                " ".join(words[:split_point]),
                " ".join(words[split_point:]),
                "fallback_split",
            )

    # -- Preprocessing orchestration (T014 + T015) ----------------------------

    async def preprocess(
        self,
        state: dict[str, Any],
        agent_count: int = 1,
    ) -> dict[str, Any]:
        """Analyze ``state["task"]`` and enrich state if above threshold.

        Returns the state dict (possibly enriched with preprocessing keys).

        State keys added on activation:
            - ``task_instructions``: str
            - ``task_data``: list[dict] (serialized TaskDataChunk list)
            - ``task_data_summary``: str
            - ``task_data_manifest``: dict (serialized TaskDataManifest)

        State keys modified on activation:
            - ``task``: set to instructions only (compact)
        """
        start_time = time.monotonic()

        if self._config.disabled:
            logger.info("task_preprocessing.disabled")
            return state

        task_text = state.get("task", "")
        if not task_text:
            return state

        task_words = len(task_text.split())
        threshold, context_window = self._compute_threshold(agent_count)

        logger.info(
            "task_preprocessing.threshold_check",
            activated=task_words > threshold,
            task_words=task_words,
            threshold=threshold,
            model=self._model_full,
            context_window=context_window,
        )

        if task_words <= threshold:
            return state

        # -- Boundary detection -----------------------------------------------
        instructions, data, method = await self._detect_boundary_with_llm_fallback(task_text)

        logger.info(
            "task_preprocessing.boundary_detected",
            method=method,
            instructions_words=len(instructions.split()) if instructions else 0,
            data_words=len(data.split()) if data else 0,
        )

        # Handle entirely instructional task (no data after split)
        if not data.strip():
            state["task_instructions"] = instructions or task_text
            state["task_data"] = []
            state["task_data_summary"] = ""
            state["task_data_manifest"] = TaskDataManifest(
                total_words=task_words,
                chunk_count=0,
                model_context_tokens=context_window,
                effective_threshold=threshold,
                boundary_method=method,
            ).to_dict()
            elapsed = (time.monotonic() - start_time) * 1000
            logger.info(
                "task_preprocessing.complete",
                total_elapsed_ms=round(elapsed, 1),
                chunks=0,
                llm_calls=1 if method == "llm_fallback" else 0,
            )
            return state

        # -- Chunking ---------------------------------------------------------
        chunk_target = int(
            context_window * self._config.chunk_context_ratio / self._config.tokens_per_word
        )
        chunk_target = max(chunk_target, 100)
        data_words_count = len(data.split())
        llm_calls = 1 if method == "llm_fallback" else 0

        # Skip chunking if data fits in one chunk target (FR-005)
        if data_words_count <= chunk_target:
            chunk = TaskDataChunk(
                chunk_id="chunk_001",
                content=data,
                words=data_words_count,
                topic_hint="",
            )
            state["task_instructions"] = instructions
            state["task"] = instructions
            state["task_data"] = [chunk.to_dict()]
            state["task_data_summary"] = ""
            state["task_data_manifest"] = TaskDataManifest(
                total_words=data_words_count,
                chunk_count=1,
                model_context_tokens=context_window,
                effective_threshold=threshold,
                boundary_method=method,
                chunks=[ChunkMeta(chunk_id="chunk_001", words=data_words_count)],
            ).to_dict()
            elapsed = (time.monotonic() - start_time) * 1000
            logger.info(
                "task_preprocessing.complete",
                total_elapsed_ms=round(elapsed, 1),
                chunks=1,
                llm_calls=llm_calls,
            )
            return state

        # Paragraph-aware chunking
        chunks = self._chunk_data(data, chunk_target)

        logger.info(
            "task_preprocessing.chunking_complete",
            chunk_count=len(chunks),
            chunk_sizes=[c.words for c in chunks],
            overlap=int(chunk_target * self._config.chunk_overlap_ratio),
        )

        # -- Summarization + manifest ----------------------------------------
        summary, topic_hints = await self._summarize_and_manifest(chunks)
        llm_calls += 1  # summarization call

        # Apply topic hints to chunks
        for chunk, hint in zip(chunks, topic_hints):
            chunk.topic_hint = hint

        manifest = TaskDataManifest(
            total_words=data_words_count,
            chunk_count=len(chunks),
            model_context_tokens=context_window,
            effective_threshold=threshold,
            boundary_method=method,
            chunks=[
                ChunkMeta(chunk_id=c.chunk_id, words=c.words, topic_hint=c.topic_hint)
                for c in chunks
            ],
        )

        # -- Enrich state -----------------------------------------------------
        state["task_instructions"] = instructions
        state["task"] = instructions
        state["task_data"] = [c.to_dict() for c in chunks]
        state["task_data_summary"] = summary
        state["task_data_manifest"] = manifest.to_dict()

        elapsed = (time.monotonic() - start_time) * 1000
        logger.info(
            "task_preprocessing.summarization_complete",
            summary_words=len(summary.split()),
            method="llm" if summary else "mechanical",
            elapsed_ms=round(elapsed, 1),
        )
        logger.info(
            "task_preprocessing.complete",
            total_elapsed_ms=round(elapsed, 1),
            chunks=len(chunks),
            llm_calls=llm_calls,
        )

        return state

    # -- Chunking (T028, placeholder for Phase 6) ----------------------------

    def _chunk_data(self, data: str, chunk_target: int) -> list[TaskDataChunk]:
        """Split *data* into paragraph-aware chunks of ~chunk_target words."""
        paragraphs = re.split(r"\n\s*\n", data)
        chunks: list[TaskDataChunk] = []
        current_words: list[str] = []
        current_paras: list[str] = []
        overlap_words = int(chunk_target * self._config.chunk_overlap_ratio)
        cap = int(chunk_target * 1.5)  # hard cap per edge case spec

        def _flush() -> None:
            if not current_words:
                return
            chunk_text = "\n\n".join(current_paras)
            chunk_id = f"chunk_{len(chunks) + 1:03d}"
            chunks.append(
                TaskDataChunk(
                    chunk_id=chunk_id,
                    content=chunk_text,
                    words=len(current_words),
                )
            )

        def _apply_overlap() -> None:
            nonlocal current_words, current_paras
            if overlap_words > 0 and len(current_words) > overlap_words:
                overlap_text = " ".join(current_words[-overlap_words:])
                current_words = overlap_text.split()
                current_paras = [overlap_text]
            else:
                current_words = []
                current_paras = []

        for para in paragraphs:
            para_words = para.split()
            if not para_words:
                continue

            # If adding this paragraph exceeds target, flush current
            if current_words and len(current_words) + len(para_words) > chunk_target:
                _flush()
                _apply_overlap()

            # Handle paragraphs larger than the cap by word-level splitting
            if len(para_words) > cap and not current_words:
                start = 0
                while start < len(para_words):
                    end = min(start + chunk_target, len(para_words))
                    segment = " ".join(para_words[start:end])
                    chunk_id = f"chunk_{len(chunks) + 1:03d}"
                    chunks.append(
                        TaskDataChunk(
                            chunk_id=chunk_id,
                            content=segment,
                            words=end - start,
                        )
                    )
                    next_start = end - overlap_words if overlap_words > 0 else end
                    if next_start <= start:
                        next_start = end
                    start = next_start
                continue

            current_words.extend(para_words)
            current_paras.append(para)

        # Flush remaining
        _flush()

        return chunks

    # -- Summarization (T030/T031, placeholder for Phase 6) ------------------

    async def _summarize_and_manifest(self, chunks: list[TaskDataChunk]) -> tuple[str, list[str]]:
        """Generate a summary and per-chunk topic hints.

        Returns ``(summary_text, topic_hints_list)``.
        On failure, falls back to a mechanical summary.
        """
        chunk_descriptions = []
        for c in chunks:
            first_sentence = c.content.split(".")[0].strip()
            if len(first_sentence) > 150:
                first_sentence = first_sentence[:147] + "..."
            chunk_descriptions.append(f"- {c.chunk_id} ({c.words} words): {first_sentence}")

        prompt = (
            "You are analyzing preprocessed data chunks from a large document.\n\n"
            "Chunks:\n" + "\n".join(chunk_descriptions) + "\n\n"
            "Provide:\n"
            "1. A concise summary of all the data (max 300 words)\n"
            "2. For each chunk, a one-sentence topic description\n\n"
            "Format your response exactly as:\n"
            "SUMMARY:\n<your summary>\n\n"
            "TOPICS:\n" + "\n".join(f"{c.chunk_id}: <topic>" for c in chunks)
        )

        for attempt in range(2):
            try:
                messages = [
                    LLMMessage(
                        role="system",
                        content="You summarize document data for routing agents.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ]
                config = LLMConfig(
                    model=self._model,
                    max_tokens=1000,
                    temperature=0.3,
                )
                response = await self._llm_provider.chat(messages, config)
                return self._parse_summary_response(response.content, chunks)
            except Exception as exc:
                logger.warning(
                    "task_preprocessing.summarization_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt == 0:
                    await asyncio.sleep(1.0)  # backoff before retry

        # Mechanical fallback
        return self._mechanical_summary(chunks)

    def _parse_summary_response(
        self, response: str, chunks: list[TaskDataChunk]
    ) -> tuple[str, list[str]]:
        """Parse the LLM summary response into summary and topic hints."""
        summary = ""
        topic_hints: list[str] = [""] * len(chunks)

        # Extract summary section
        summary_match = re.search(r"SUMMARY:\s*\n(.*?)(?:\n\s*TOPICS:|$)", response, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()

        # Extract topic hints
        for i, chunk in enumerate(chunks):
            pattern = re.escape(chunk.chunk_id) + r":\s*(.+)"
            m = re.search(pattern, response)
            if m:
                topic_hints[i] = m.group(1).strip()

        return summary, topic_hints

    def _mechanical_summary(self, chunks: list[TaskDataChunk]) -> tuple[str, list[str]]:
        """Generate a mechanical summary from chunk metadata (fallback)."""
        total_words = sum(c.words for c in chunks)
        lines = [
            f"Data contains {total_words} words across {len(chunks)} chunks.",
        ]
        topic_hints: list[str] = []
        for c in chunks:
            first_sentence = c.content.split(".")[0].strip()
            if len(first_sentence) > 100:
                first_sentence = first_sentence[:97] + "..."
            topic_hints.append(first_sentence)
            lines.append(f"- {c.chunk_id} ({c.words} words): {first_sentence}")

        return "\n".join(lines), topic_hints
