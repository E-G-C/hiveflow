"""Document Pipeline - Orchestrates document loading, chunking, and state injection.

Validates paths, detects formats, dispatches to loaders, chunks content,
estimates tokens, enforces size limits, and produces state-ready dictionaries.
"""

from pathlib import Path
from typing import Any

import structlog

from hiveflow.plugins.documents import (
    Document,
    DocumentChunk,
    DocumentLoaderRegistry,
    chunk_text,
)
from hiveflow.validation.path_security import validate_document_path

logger = structlog.get_logger()

# Default 50 MB
DEFAULT_MAX_TOTAL_BYTES = 50 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


class DocumentPipeline:
    """Orchestrates document loading, chunking, and state injection."""

    def __init__(
        self,
        registry: DocumentLoaderRegistry | None = None,
        working_dir: Path | None = None,
        allowed_paths: list[Path] | None = None,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        embedding_provider: Any = None,
        similarity_threshold: float = 0.35,
    ) -> None:
        self.registry = registry or DocumentLoaderRegistry()
        self.registry.discover()
        self.working_dir = (working_dir or Path.cwd()).resolve()
        self.allowed_paths = allowed_paths
        self.max_total_bytes = max_total_bytes
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_provider = embedding_provider
        self.similarity_threshold = similarity_threshold
        logger.debug(
            "DocumentPipeline initialized: working_dir=%s, max_bytes=%d, "
            "chunk_size=%d, chunk_overlap=%d",
            self.working_dir,
            self.max_total_bytes,
            self.chunk_size,
            self.chunk_overlap,
        )

    async def load(
        self,
        inputs: list[str | dict[str, str]],
    ) -> tuple[list[dict[str, Any]], str]:
        """Load and process documents from file paths or inline content.

        Args:
            inputs: List of file path strings or inline content dicts
                with required keys 'name' and 'content'.

        Returns:
            Tuple of (list of document state dicts, summary string).

        Raises:
            FileNotFoundError: If a file path does not exist.
            ValueError: If format unsupported, path traversal, size limit
                exceeded, or duplicate names.
        """
        documents: list[Document] = []
        seen_names: set[str] = set()
        total_bytes = 0

        logger.info("Loading %d document input(s)", len(inputs))

        for item in inputs:
            if isinstance(item, dict):
                if "bytes" in item:
                    doc = await self._load_bytes(item)
                    logger.debug("Loaded bytes document: %s (%d bytes)", doc.name, doc.size_bytes)
                else:
                    doc = self._load_inline(item)
                    logger.debug("Loaded inline document: %s (%d bytes)", doc.name, doc.size_bytes)
            else:
                doc = await self._load_file(item)
                logger.debug("Loaded file document: %s (%d bytes)", doc.name, doc.size_bytes)

            # Check for duplicate names
            if doc.name in seen_names:
                logger.error("Duplicate document name: %s", doc.name)
                raise ValueError(f"Duplicate document name: '{doc.name}'")
            seen_names.add(doc.name)

            # Accumulate size
            total_bytes += doc.size_bytes
            if total_bytes > self.max_total_bytes:
                limit_mb = self.max_total_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                logger.error(
                    "Total document size %.1f MB exceeds limit %.1f MB",
                    total_mb,
                    limit_mb,
                )
                raise ValueError(
                    f"Total document size ({total_mb:.1f} MB) exceeds limit ({limit_mb:.1f} MB)"
                )

            # Chunk the document
            self._chunk_document(doc)
            logger.debug(
                "Chunked %s: %d chunks, ~%d tokens",
                doc.name,
                len(doc.chunks),
                doc.total_tokens_estimate,
            )
            documents.append(doc)

        # Convert to state dicts
        state_dicts = [doc.to_state_dict() for doc in documents]

        # Build summary
        summary = self._build_summary(documents)
        logger.info(
            "Document loading complete: %d documents, %d total bytes",
            len(documents),
            total_bytes,
        )

        return state_dicts, summary

    async def _load_file(self, path: str) -> Document:
        """Load a document from a file path.

        Tries all matching loaders in order, falling back to the next
        if one fails (e.g. python-docx can't read a file but MarkItDown can).
        """
        validated_path = validate_document_path(path, self.working_dir, self.allowed_paths)

        # Find all loaders for this file extension
        loaders = self.registry.get_all_loaders_for_file(validated_path)
        if not loaders:
            supported = set()
            for pid in self.registry.list_ids():
                ldr = self.registry.get(pid)
                if ldr:
                    supported.update(ldr.supported_extensions)
            ext = validated_path.suffix
            logger.error(
                "Unsupported format '%s' for %s; supported: %s",
                ext,
                path,
                sorted(supported),
            )
            raise ValueError(
                f"Unsupported document format '{ext}'. Supported: {', '.join(sorted(supported))}"
            )

        # Try each loader in order; fall back to the next on failure
        last_error: Exception | None = None
        for loader in loaders:
            try:
                logger.debug(
                    "Trying loader '%s' for %s",
                    loader.plugin_id,
                    validated_path.name,
                )
                doc = await loader.load(validated_path)

                # Set pipeline-specific fields
                try:
                    doc.name = str(validated_path.relative_to(self.working_dir))
                except ValueError:
                    doc.name = str(validated_path)
                doc.format = validated_path.suffix.lstrip(".")
                doc.size_bytes = validated_path.stat().st_size
                doc.total_tokens_estimate = self._estimate_tokens(doc.content)

                return doc
            except (FileNotFoundError, PermissionError, IsADirectoryError):
                raise  # Filesystem errors: no point trying another loader
            except Exception as exc:
                last_error = exc
                remaining = len(loaders) - loaders.index(loader) - 1
                if remaining > 0:
                    logger.warning(
                        "Loader '%s' failed for %s: %s — trying %d more loader(s)",
                        loader.plugin_id,
                        validated_path.name,
                        exc,
                        remaining,
                    )
                else:
                    logger.error(
                        "Loader '%s' failed for %s: %s — no more loaders to try",
                        loader.plugin_id,
                        validated_path.name,
                        exc,
                    )

        # All loaders failed
        raise RuntimeError(
            f"All loaders failed for '{path}'. Last error: {last_error}"
        ) from last_error

    def _load_inline(self, item: dict[str, str]) -> Document:
        """Load a document from an inline content dict."""
        if "name" not in item or "content" not in item:
            raise ValueError("Inline document dict must have 'name' and 'content' keys")

        content = item["content"]
        name = item["name"]
        size_bytes = len(content.encode("utf-8"))

        return Document(
            content=content,
            source="inline",
            name=name,
            format="txt",
            size_bytes=size_bytes,
            total_tokens_estimate=self._estimate_tokens(content),
        )

    async def _load_bytes(self, item: dict[str, Any]) -> Document:
        """Load a document from in-memory bytes via loader plugin."""
        if "name" not in item or "bytes" not in item:
            raise ValueError("Bytes document dict must have 'name' and 'bytes' keys")

        name = item["name"]
        data = item["bytes"]
        ext = Path(name).suffix.lower()

        # Find loader for extension
        loaders = [
            self.registry.get(pid)
            for pid in self.registry.list_ids()
            if self.registry.get(pid)
            and ext in [e.lower() for e in self.registry.get(pid).supported_extensions]
        ]

        if not loaders:
            # Fall back to plain text for unknown extensions
            content = data.decode("utf-8", errors="replace")
            return Document(
                content=content,
                source="bytes",
                name=name,
                format=ext.lstrip(".") or "txt",
                size_bytes=len(data),
                total_tokens_estimate=self._estimate_tokens(content),
            )

        for loader in loaders:
            try:
                doc = await loader.load_from_bytes(data, name)
                doc.source = "bytes"
                doc.name = name
                doc.size_bytes = len(data)
                doc.total_tokens_estimate = self._estimate_tokens(doc.content)
                return doc
            except Exception:
                continue

        # All loaders failed — fall back to text
        content = data.decode("utf-8", errors="replace")
        return Document(
            content=content,
            source="bytes",
            name=name,
            format=ext.lstrip(".") or "txt",
            size_bytes=len(data),
            total_tokens_estimate=self._estimate_tokens(content),
        )

    def _chunk_document(self, doc: Document) -> None:
        """Split a document into chunks and attach them."""
        if not doc.content:
            # Empty content: create a single empty chunk
            chunk = DocumentChunk(
                content="",
                source=doc.source,
                chunk_index=0,
                total_chunks=1,
                token_estimate=0,
            )
            doc.chunks = [chunk]
            return

        text_chunks = chunk_text(doc.content, self.chunk_size, self.chunk_overlap)
        total = len(text_chunks)
        chunks = []
        for i, text in enumerate(text_chunks):
            chunk = DocumentChunk(
                content=text,
                source=doc.source,
                chunk_index=i,
                total_chunks=total,
                token_estimate=self._estimate_tokens(text),
            )
            chunks.append(chunk)
        doc.chunks = chunks

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using word_count / 0.75 approximation."""
        word_count = len(text.split())
        return int(word_count / 0.75)

    def _build_summary(self, documents: list[Document]) -> str:
        """Build a human-readable summary of loaded documents."""
        if not documents:
            return "No documents loaded."

        total_tokens = sum(d.total_tokens_estimate for d in documents)
        doc_descriptions = []
        for d in documents:
            doc_descriptions.append(
                f"{d.name} ({len(d.chunks)} chunks, ~{d.total_tokens_estimate} tokens)"
            )

        count = len(documents)
        docs_str = ", ".join(doc_descriptions)
        return (
            f"{count} document{'s' if count != 1 else ''} loaded: "
            f"{docs_str} (~{total_tokens} total tokens)"
        )

    async def load_instructions_file(self, path: str) -> str:
        """Read instructions from a file path.

        Args:
            path: File path to read as instructions.

        Returns:
            File content as UTF-8 string.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If path security validation fails.
        """
        logger.debug("Loading instructions file: %s", path)
        validated_path = validate_document_path(path, self.working_dir, self.allowed_paths)
        content = validated_path.read_text(encoding="utf-8")
        logger.info(
            "Loaded instructions from %s (%d chars)",
            validated_path.name,
            len(content),
        )
        return content

    async def generate_summaries(
        self,
        documents: list[dict[str, Any]],
        state: dict[str, Any],
        llm_provider: Any,
        max_tokens: int = 200,
        model: str = "",
    ) -> dict[str, str]:
        """Generate LLM-based summaries for documents.

        Uses the SYSTEM_SUMMARIZER prompt template and caches results
        in state["_document_summaries"] to avoid re-summarizing.

        Args:
            documents: Document state dicts to summarize.
            state: Workflow state (for caching under _document_summaries).
            llm_provider: LLM provider for summary generation.
            max_tokens: Max tokens per summary.
            model: Model/deployment name to use. If empty, resolved from
                the global HiveFlowConfig FAST_LLM tier.

        Returns:
            Dict mapping document name → summary string.
        """
        if not model:
            try:
                from hiveflow.core.config import get_config

                cfg = get_config()
                raw = cfg.FAST_LLM
                model = raw.split(":", 1)[-1] if ":" in raw else raw
            except Exception:
                pass

        cache = state.setdefault("_document_summaries", {})

        for doc in documents:
            name = doc.get("name", "unknown")
            if name in cache:
                continue  # Already cached

            # Build document text from chunks
            chunks = doc.get("chunks", [])
            text = "\n".join(c.get("content", "") for c in chunks if isinstance(c, dict))
            if not text.strip():
                cache[name] = f"[Empty document: {name}]"
                continue

            # Generate summary via LLM
            try:
                from hiveflow.core.prompts import SYSTEM_SUMMARIZER
                from hiveflow.plugins.llm import LLMConfig, LLMMessage

                prompt = SYSTEM_SUMMARIZER.render(
                    text=text[:10000],  # Limit input to avoid context overflow
                    max_tokens=str(max_tokens),
                )

                messages = [
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=f"Summarize the document '{name}'."),
                ]

                response = await llm_provider.chat(
                    messages, LLMConfig(model=model, max_tokens=max_tokens)
                )
                cache[name] = response.content.strip()
                logger.info("Generated summary for %s (%d chars)", name, len(cache[name]))

            except Exception as exc:
                logger.warning(
                    "Failed to generate summary for %s: %s — using metadata fallback",
                    name,
                    exc,
                )
                cache[name] = (
                    f"{name}: {doc.get('format', '?')} format, "
                    f"{doc.get('chunk_count', 0)} chunks, "
                    f"~{doc.get('total_tokens_estimate', 0)} tokens"
                )

        return cache

    def scope_for_agent(
        self,
        documents: list[dict[str, Any]],
        agent_def: Any,
        task: str = "",  # noqa: ARG002 — reserved for relevant_chunks mode
        state: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter and transform documents per agent scoping config.

        Args:
            documents: List of document state dicts.
            agent_def: AgentDefinition with documents, document_mode,
                max_document_tokens fields.
            task: Current task string (used for relevant_chunks mode).
            state: Optional workflow state (for reading summary cache).

        Returns:
            Filtered/transformed document list.
        """
        mode = getattr(agent_def, "document_mode", "none")
        doc_names = getattr(agent_def, "documents", None)
        max_tokens = getattr(agent_def, "max_document_tokens", None)

        agent_id = getattr(agent_def, "id", "unknown")
        logger.debug(
            "Scoping documents for agent '%s': mode=%s, names=%s, max_tokens=%s",
            agent_id,
            mode,
            doc_names,
            max_tokens,
        )

        if mode == "none":
            logger.debug("Agent '%s' mode=none, returning empty", agent_id)
            return []

        # Filter by document names if specified
        if doc_names is not None:
            if len(doc_names) == 0:
                return []
            filtered = [d for d in documents if d.get("name") in doc_names]
        else:
            # None = all documents
            filtered = list(documents)

        if mode == "metadata_only":
            return [
                {
                    "name": d["name"],
                    "format": d["format"],
                    "size_bytes": d["size_bytes"],
                    "chunk_count": d["chunk_count"],
                    "total_tokens_estimate": d["total_tokens_estimate"],
                }
                for d in filtered
            ]

        if mode == "full":
            result = filtered
        elif mode == "relevant_chunks":
            if self.embedding_provider is not None and task:
                # Use semantic filtering when embedding provider is available
                result = filtered  # Will be filtered by _filter_relevant_chunks
                logger.info(
                    "relevant_chunks mode with embedding provider for agent '%s'",
                    agent_id,
                )
                # Mark for async filtering (caller must call filter_relevant_chunks)
                for d in result:
                    d["_needs_relevance_filter"] = True
                    d["_relevance_query"] = task
            else:
                # Fallback to full when no embedding provider
                logger.warning(
                    "relevant_chunks mode requested but no embedding provider configured; "
                    "falling back to full mode"
                )
                result = filtered
        elif mode == "summary":
            # Use cached summaries from generate_summaries() if available
            cache = (state or {}).get("_document_summaries", {})
            result = []
            for d in filtered:
                name = d["name"]
                if name in cache:
                    result.append(
                        {
                            "name": name,
                            "format": d["format"],
                            "size_bytes": d["size_bytes"],
                            "chunk_count": 1,
                            "total_tokens_estimate": len(cache[name].split()) * 2,
                            "chunks": [{"index": 0, "content": cache[name]}],
                        }
                    )
                else:
                    logger.warning(
                        "No cached summary for '%s'; falling back to metadata_only", name
                    )
                    result.append(
                        {
                            "name": name,
                            "format": d["format"],
                            "size_bytes": d["size_bytes"],
                            "chunk_count": d["chunk_count"],
                            "total_tokens_estimate": d["total_tokens_estimate"],
                        }
                    )
            return result
        else:
            result = filtered

        # Apply token budget if set
        if max_tokens is not None:
            result = self._apply_token_budget(result, max_tokens)

        return result

    def _apply_token_budget(
        self,
        documents: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Truncate document chunks to fit within a token budget."""
        remaining = max_tokens
        result = []

        for doc in documents:
            if remaining <= 0:
                break

            chunks = doc.get("chunks", [])
            kept_chunks = []
            for chunk in chunks:
                content = chunk.get("content", "")
                chunk_tokens = int(len(content.split()) / 0.75)
                if chunk_tokens <= remaining:
                    kept_chunks.append(chunk)
                    remaining -= chunk_tokens
                else:
                    # Truncate this chunk to fit
                    words = content.split()
                    words_to_keep = int(remaining * 0.75)
                    if words_to_keep > 0:
                        truncated = " ".join(words[:words_to_keep])
                        kept_chunks.append({"index": chunk["index"], "content": truncated})
                    remaining = 0
                    break

            if kept_chunks:
                truncated_doc = dict(doc)
                truncated_doc["chunks"] = kept_chunks
                truncated_doc["chunk_count"] = len(kept_chunks)
                result.append(truncated_doc)

        return result

    async def filter_relevant_chunks(
        self,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply semantic filtering to documents marked for relevance filtering.

        Embeds each chunk, compares against the query, and keeps only chunks
        above the similarity threshold. Documents without the relevance marker
        are returned as-is.

        Args:
            documents: Document list from scope_for_agent.

        Returns:
            Filtered documents with only relevant chunks.
        """
        if self.embedding_provider is None:
            return documents

        result = []
        for doc in documents:
            query = doc.pop("_relevance_query", None)
            needs_filter = doc.pop("_needs_relevance_filter", False)

            if not needs_filter or not query:
                result.append(doc)
                continue

            chunks = doc.get("chunks", [])
            if not chunks:
                result.append(doc)
                continue

            # Embed query and all chunk texts
            chunk_texts = [c.get("content", "") for c in chunks]
            try:
                query_embedding = await self.embedding_provider.embed_single(query)
                chunk_embeddings = await self.embedding_provider.embed(chunk_texts)
            except Exception:
                logger.warning(
                    "Embedding failed during relevant_chunks filtering; "
                    "falling back to full content",
                    exc_info=True,
                )
                result.append(doc)
                continue

            # Compute cosine similarities and filter
            relevant_chunks = []
            for chunk, chunk_vec in zip(chunks, chunk_embeddings):
                sim = self._cosine_similarity(query_embedding, chunk_vec)
                if sim >= self.similarity_threshold:
                    chunk["_relevance_score"] = sim
                    relevant_chunks.append(chunk)

            # Sort by relevance descending
            relevant_chunks.sort(key=lambda c: c.get("_relevance_score", 0), reverse=True)

            if relevant_chunks:
                filtered_doc = dict(doc)
                filtered_doc["chunks"] = relevant_chunks
                filtered_doc["chunk_count"] = len(relevant_chunks)
                result.append(filtered_doc)
                logger.info(
                    "relevant_chunks filtered: %d/%d chunks kept (threshold=%.2f)",
                    len(relevant_chunks),
                    len(chunks),
                    self.similarity_threshold,
                )
            else:
                # If nothing passes threshold, keep all (graceful fallback)
                logger.warning(
                    "No chunks passed relevance threshold %.2f; keeping all",
                    self.similarity_threshold,
                )
                result.append(doc)

        return result

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot: float = sum(x * y for x, y in zip(a, b))
        norm_a: float = sum(x * x for x in a) ** 0.5
        norm_b: float = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
