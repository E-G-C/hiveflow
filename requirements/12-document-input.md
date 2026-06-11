[< Back to Index](README.md)

---

## Document Input Pipeline

Workflows frequently need to process **user-supplied documents** as source
material — a presentation transcript to rewrite, a contract to analyze, a
codebase to review, a dataset to summarize. The framework provides a first-class
mechanism for feeding documents into workflows, connecting document loader
plugins and chunking infrastructure to the workflow engine and agent execution
model.

### Current State

The document input pipeline is implemented and operational across all three
design phases:

- ✅ **`DocumentLoaderPlugin`** system (`plugins/documents/`) with plugin
  registry, 10 format-specific loaders, and a `MarkItDownLoader` universal
  fallback — all registered as `hiveflow.document_loaders` entry points
- ✅ **`DocumentPipeline`** (`core/documents.py`) orchestrates loading, chunking,
  validation, size-limit enforcement, and state injection
- ✅ **`chunk_text()`** utility for splitting large content into LLM-sized chunks
  (word-count based, configurable overlap)
- ✅ **Context compression** pipeline (`core/compression.py`) with deduplication,
  scoring, and budget fitting
- ✅ **File-path and inline loading** via `documents` parameter on
  `HiveFlow.run()` and `WorkflowEngine.execute()`
- ✅ **Instructions-from-file** via `instructions_file` parameter on
  `WorkflowEngine.execute()` and `--instructions-file` CLI argument
- ✅ **Per-agent document scoping** via `documents`, `document_mode`, and
  `max_document_tokens` fields on `AgentDefinition`
- ✅ **`DocumentRetrieverTool`** (`plugins/tools/document_retriever.py`)
  registered as `hiveflow.tools` entry point for on-demand agent-driven retrieval
- ✅ **Path security** validation (`validation/path_security.py`) for document
  file paths
- ✅ **API endpoints** for document upload, listing, and retrieval in the FastAPI
  server
- ✅ **CLI support** with `--doc` (repeatable), `--instructions`,
  `--instructions-file`, and stdin piping (`-`)

### Remaining Enhancements

The following enhancements build on the existing implementation. Each is
additive — no existing API signatures, semantics, or behavior are changed.

---

#### Enhancement 1: `instructions_file` on `HiveFlow.run()`

**Status:** `instructions_file` is available on `WorkflowEngine.execute()` and
the CLI, but **not yet surfaced** on the top-level `HiveFlow.run()` Python API.

**Goal:** Allow Python API callers to pass `instructions_file` without directly
interacting with the engine.

**Change:**

Add an optional `instructions_file: str | None = None` parameter to
`HiveFlow.run()`. It is mutually exclusive with the `task` parameter — when
`instructions_file` is provided, `task` should be an empty string or omitted.
The method reads the file (via `DocumentPipeline.load_instructions_file()`) and
uses its content as the task string before passing it to the engine.

```python
# Current API
session = await hive.run(team="content_rewriter", task="Rewrite as a blog post")

# Enhanced API — load complex instructions from a file
session = await hive.run(
    team="content_rewriter",
    task="",
    instructions_file="./prompts/rewrite-instructions.md",
    documents=["./transcript.txt"],
)
```

Rules:
- `task` (non-empty) and `instructions_file` are **mutually exclusive** —
  providing both raises `ValueError`.
- `instructions_file` accepts any text-based file (`.txt`, `.md`, `.rst`, etc.).
  Read as UTF-8, content becomes the `task` string verbatim.
- File-based instructions are **not** chunked or processed through the document
  loader pipeline.

---

#### Enhancement 2: `load_from_bytes()` on `DocumentLoaderPlugin`

**Status:** The `DocumentLoaderPlugin` base class defines only
`async load(file_path: str | Path) -> Document`. There is no method for
loading from in-memory byte streams.

**Goal:** Support API upload and in-memory scenarios where file content arrives
as bytes without a filesystem path.

**Change:**

Add `load_from_bytes()` as an **optional** (non-abstract) method on
`DocumentLoaderPlugin` with a default implementation that writes to a temp file
and delegates to `load()`. Loaders may override this for efficiency.

```python
class DocumentLoaderPlugin(BasePlugin):
    # Existing abstract methods remain unchanged:
    #   plugin_id, description, supported_extensions, load(file_path)

    async def load_from_bytes(self, data: bytes, filename: str) -> Document:
        """Load a document from in-memory bytes.

        Default implementation writes to a temp file and delegates to load().
        Subclasses may override for direct byte-stream processing.

        Args:
            data: Raw file bytes.
            filename: Original filename (used for extension detection and naming).

        Returns:
            Parsed Document.
        """
        import tempfile
        from pathlib import Path

        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            return await self.load(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
```

This is **backward compatible** — existing third-party loaders that only
implement `load()` inherit the default without changes.

---

#### Enhancement 3: `summary` Document Mode (LLM-based)

**Status:** The `summary` document mode is defined in `DocumentMode` and
accepted by `AgentDefinition.document_mode`, but `scope_for_agent()` currently
falls back to `metadata_only` with a warning:

> *"summary mode requested but not yet implemented; falling back to
> metadata_only"*

**Goal:** Implement actual LLM-driven summarization for the `summary` mode so
agents receive a condensed version of document content instead of raw chunks.

**Change:**

When `document_mode="summary"` is requested for an agent:

1. Use the configured `FAST_LLM` model to generate a concise summary of each
   document's content.
2. Replace the document's `chunks` list with a single summary chunk.
3. Cache summaries in state so the same document is not re-summarized for
   multiple agents.

Fallback behavior (no `FAST_LLM` configured) should remain `metadata_only` with
a warning — matching the current behavior.

---

#### Enhancement 4: Prompt Template Variables for Documents

**Status:** The prompt template system does not currently resolve document
metadata variables.

**Goal:** Make document metadata available as template variables so prompt
templates can reference them dynamically.

**Change:**

When documents are loaded into state, register the following variables for
prompt template resolution:

| Variable              | Value                                                         |
| --------------------- | ------------------------------------------------------------- |
| `$document_count`     | Number of documents loaded (integer)                          |
| `$document_names`     | Comma-separated list of document names                        |
| `$document_summary`   | The `document_summary` string from state                      |

These are purely additive — templates that don't reference them are unaffected.

---

### Reference: Current Architecture

This section documents the implemented pipeline for reference. It is not a
requirement — it describes the baseline.

#### Python API

```python
from hiveflow import HiveFlow

hive = HiveFlow()

# Pass documents by file path
session = await hive.run(
    team="content_rewriter",
    task="Rewrite this transcript as a blog post",
    documents=["./transcript.txt", "./speaker-notes.md"],
)

# Pass documents by raw content (in-memory)
session = await hive.run(
    team="contract_analyzer",
    task="Identify risks in this contract",
    documents=[{"name": "contract.txt", "content": "AGREEMENT dated..."}],
)

# Mix of file paths and inline content
session = await hive.run(
    team="research_report",
    task="Summarize findings from these sources",
    documents=[
        "./data/report.pdf",
        {"name": "interview.txt", "content": "Q: Tell us about..."},
    ],
)
```

#### CLI

```bash
# Single document
hiveflow run --template content_rewriter \
    --instructions "Rewrite as a blog post" \
    --doc ./transcript.txt

# Multiple documents
hiveflow run --template contract_analyzer \
    --instructions "Identify risks" \
    --doc ./contract.pdf \
    --doc ./amendment.docx

# Pipe content from stdin
cat presentation.txt | hiveflow run --template rewriter --instructions "..." --doc -

# Instructions from a file
hiveflow run --template content_rewriter \
    --instructions-file ./prompts/rewrite-instructions.md \
    --doc ./transcript.txt

# Instructions from stdin
cat complex-prompt.md | hiveflow run --template research_report --instructions -
```

#### Internal Pipeline

```
User documents (file paths, raw content, stdin)
  ↓
DocumentPipeline.load()                # Validation, dedup, size limits
  ↓
DocumentLoaderPlugin.load()            # Format-specific parsing → Document
  ↓
chunk_text()                           # Word-count chunking with overlap
  ↓
State["documents"]                     # List of document state dicts
State["document_summary"]             # Human-readable summary string
  ↓
Agent._summarize_state()               # Per-agent scoping via scope_for_agent()
  ↓
Agent context (via _build_messages)    # Injected as ### {name}\n{content}
```

#### State Shape

```json
{
  "task": "Rewrite this transcript as a blog post",
  "documents": [
    {
      "name": "transcript.txt",
      "format": "txt",
      "size_bytes": 24500,
      "chunks": [
        {"index": 0, "content": "Hello everyone, welcome to today's talk..."},
        {"index": 1, "content": "...and that brings us to the key insight..."}
      ],
      "chunk_count": 4,
      "total_tokens_estimate": 6100
    }
  ],
  "document_summary": "1 document loaded: transcript.txt (4 chunks, ~6100 tokens)"
}
```

#### Per-Agent Document Scoping

Configured via `AgentDefinition` fields:

| Field                 | Type                  | Default   | Semantics                                     |
| --------------------- | --------------------- | --------- | --------------------------------------------- |
| `documents`           | `list[str] \| None`   | `None`    | `None` = all documents, `[]` = none            |
| `document_mode`       | `str`                 | `"none"`  | One of: `full`, `relevant_chunks`, `summary`, `metadata_only`, `none` |
| `max_document_tokens` | `int \| None`         | `None`    | Per-agent token budget for document content    |

When `document_mode` is `"none"` (the default), the agent receives no document
content regardless of the `documents` list.

#### Document Loader Plugins

| Format                           | Loader              | Plugin ID     | Package/Library   |
| -------------------------------- | ------------------- | ------------- | ----------------- |
| `.txt`, `.text`, `.log`, `.csv`, `.tsv` | `PlainTextLoader`   | `text`        | Built-in          |
| `.md`, `.markdown`, `.mdown`, `.mkd`   | `MarkdownLoader`    | `markdown`    | Built-in          |
| `.pdf`                           | `PDFLoader`         | `pdf`         | `pymupdf`         |
| `.docx`                          | `DocxLoader`        | `docx`        | `python-docx`     |
| `.pptx`                          | `PptxLoader`        | `pptx`        | `python-pptx`     |
| `.xlsx`, `.xls`                  | `ExcelLoader`       | `excel`       | `openpyxl`        |
| `.html`, `.htm`                  | `HTMLLoader`        | `html`        | `beautifulsoup4`  |
| `.json`, `.jsonl`                | `JSONLoader`        | `json`        | Built-in          |
| `.xml`                           | `XMLLoader`         | `xml`         | Built-in          |
| *(many formats)*                 | `MarkItDownLoader`  | `markitdown`  | `markitdown`      |

All loaders implement the `DocumentLoaderPlugin` abstract base class:

```python
class DocumentLoaderPlugin(BasePlugin):
    @property
    @abstractmethod
    def plugin_id(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]: ...

    @abstractmethod
    async def load(self, file_path: str | Path) -> Document: ...
```

Loaders are discovered via the `hiveflow.document_loaders` entry point group
and the `DocumentLoaderRegistry`.

#### DocumentRetrieverTool

Registered as `document_retriever` in the `hiveflow.tools` entry point group.
Allows `tool_user` agents to fetch document content on demand.

Parameters: `document_name` (optional), `query` (optional, semantic search),
`chunk_indices` (optional), `max_tokens` (optional).

#### API Endpoints

| Method | Path                                       | Description                              |
| ------ | ------------------------------------------ | ---------------------------------------- |
| POST   | `/workflows/start`                         | Start workflow (JSON: `team`, `documents`, `instructions`, `instructions_file`) |
| POST   | `/workflows/start/upload`                  | Start workflow with multipart file upload |
| POST   | `/workflows/{workflow_id}/documents`       | Upload documents to a running workflow   |
| GET    | `/workflows/{workflow_id}/documents`       | List loaded documents and metadata       |
| GET    | `/workflows/{workflow_id}/documents/{name}`| Get document chunks/content              |

---

---

[Next: Coverage Summary (Appendix) >](99-appendix.md)
