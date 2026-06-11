# Feature Specification: Document Input Pipeline Enhancements

**Feature Branch**: `009-document-input-pipeline`  
**Created**: 2026-02-27  
**Status**: Draft  
**Input**: User description: "Document input pipeline enhancements: instructions_file on HiveFlow.run(), load_from_bytes() on loaders, LLM-based summary document mode, and prompt template variables for documents" (derived from `requirements/12-document-input.md`)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Load Instructions from a File via Python API (Priority: P1)

A Python API user has complex, multi-paragraph instructions for a workflow that are maintained in a separate file (e.g., a markdown file with detailed rewriting guidelines). They want to pass this instructions file directly to `HiveFlow.run()` instead of embedding the instructions as a string in their code or manually reading the file themselves.

**Why this priority**: This is the most requested API gap — `instructions_file` already works on the CLI and `WorkflowEngine.execute()`, but the top-level Python API doesn't expose it. Closing this gap provides immediate value with minimal risk.

**Independent Test**: Can be fully tested by creating an instructions file, calling `HiveFlow.run(instructions_file=path)`, and verifying the file contents are used as the task string.

**Acceptance Scenarios**:

1. **Given** a text file containing workflow instructions, **When** `HiveFlow.run()` is called with `instructions_file` pointing to that file and `task` set to an empty string, **Then** the file's contents are read as UTF-8 and used as the task string for the workflow.
2. **Given** both `task` (non-empty) and `instructions_file` are provided, **When** `HiveFlow.run()` is called, **Then** the system raises a clear error indicating the two parameters are mutually exclusive.
3. **Given** an `instructions_file` path that does not exist, **When** `HiveFlow.run()` is called, **Then** the system raises a file-not-found error with the specified path.
4. **Given** an instructions file in any text-based format (`.txt`, `.md`, `.rst`), **When** it is loaded, **Then** the content is read verbatim as UTF-8 without any chunking or document-loader processing.

---

### User Story 2 - Load Documents from In-Memory Bytes (Priority: P2)

A developer building an API integration receives document content as byte streams (e.g., from an HTTP upload, a database blob, or an in-memory buffer) rather than as files on disk. They need to load these byte streams through the document loader pipeline without first writing them to temporary files manually.

**Why this priority**: Enables API-first and serverless deployment patterns where documents arrive as uploads. The default implementation delegates to file-based loading for backward compatibility, while allowing loader authors to optimize for direct byte processing.

**Independent Test**: Can be fully tested by passing raw bytes and a filename to `load_from_bytes()`, and verifying the returned document matches what `load()` produces for the same content on disk.

**Acceptance Scenarios**:

1. **Given** raw document bytes and an original filename, **When** `load_from_bytes(data, filename)` is called on any document loader, **Then** the loader returns a parsed Document identical to what `load()` would produce for the same file content.
2. **Given** a loader that does not override `load_from_bytes()`, **When** the default implementation is used, **Then** it writes bytes to a temporary file, delegates to `load()`, and cleans up the temporary file afterward.
3. **Given** a loader that overrides `load_from_bytes()` for efficiency, **When** the override is called, **Then** it processes bytes directly without creating temporary files.
4. **Given** bytes with a filename whose extension is not supported by the loader, **When** `load_from_bytes()` is called, **Then** the system reports an unsupported format error consistent with how `load()` handles unsupported extensions.

---

### User Story 3 - Receive Condensed Document Summaries as an Agent (Priority: P2)

A workflow author configures an agent with `document_mode="summary"` so the agent receives a concise LLM-generated summary of each document rather than raw chunks. This is useful for agents that need document awareness (e.g., a reviewer or planner) but don't need full content — reducing token usage while preserving key information.

**Why this priority**: The `summary` document mode is already defined in the schema and accepted in configuration, but currently falls back to `metadata_only` with a warning. Implementing it completes a promised capability and improves token efficiency for summary-oriented agents.

**Independent Test**: Can be fully tested by loading a document, requesting `document_mode="summary"` for an agent, and verifying the agent receives a single summary chunk per document (not raw chunks) that captures the document's key content.

**Acceptance Scenarios**:

1. **Given** a document loaded into workflow state and an agent configured with `document_mode="summary"`, **When** the document is scoped for that agent, **Then** the agent receives a single condensed summary chunk per document instead of the full chunk list.
2. **Given** the same document requested in summary mode by multiple agents, **When** the second agent's scoping runs, **Then** the cached summary from the first request is reused without re-invoking the LLM.
3. **Given** no LLM provider is configured (e.g., the Fast LLM tier is unavailable), **When** summary mode is requested, **Then** the system falls back to `metadata_only` with a warning log, matching the current fallback behavior.
4. **Given** a very large document, **When** summary mode is requested, **Then** the summary respects a reasonable token budget (e.g., MAX_SUMMARY_LENGTH from configuration) and does not exceed it.

---

### User Story 4 - Reference Document Metadata in Prompt Templates (Priority: P3)

A workflow author writes prompt templates that dynamically reference document context — how many documents are loaded, their names, and the summary string. This allows prompts to adapt to the input without hardcoding document details.

**Why this priority**: This is a quality-of-life enhancement that makes prompts more dynamic. It builds on the existing prompt template variable system and adds document-specific variables. Lower priority because prompts can always reference state directly via dotted-path variables.

**Independent Test**: Can be fully tested by loading documents into state, rendering a prompt template that uses `$document_count`, `$document_names`, and `$document_summary`, and verifying the variables are substituted with correct values.

**Acceptance Scenarios**:

1. **Given** documents loaded into workflow state, **When** a prompt template contains `$document_count`, **Then** it is replaced with the integer count of loaded documents.
2. **Given** documents loaded into workflow state, **When** a prompt template contains `$document_names`, **Then** it is replaced with a comma-separated list of document names.
3. **Given** documents loaded into workflow state, **When** a prompt template contains `$document_summary`, **Then** it is replaced with the human-readable summary string from state.
4. **Given** no documents are loaded, **When** a prompt template contains document variables, **Then** `$document_count` resolves to `0`, `$document_names` resolves to an empty string, and `$document_summary` resolves to an empty string.

---

### Edge Cases

- What happens when `instructions_file` points to an empty file? The task string is set to an empty string; the workflow proceeds with no task description (agents see an empty task).
- What happens when `load_from_bytes()` receives zero-length bytes? The loader raises a validation error indicating the document is empty.
- What happens when a document loader's `load()` fails during the temp-file delegation in default `load_from_bytes()`? The temporary file is cleaned up regardless of the error, and the original exception is re-raised.
- What happens when the summary LLM call fails for one document in a multi-document workflow? The failed document falls back to `metadata_only` for that agent; other documents' summaries are unaffected.
- What happens when document variables are used in a prompt but documents haven't been loaded yet into state? The variables resolve to their default values (`0`, empty string, empty string).

## Requirements *(mandatory)*

### Functional Requirements

**Enhancement 1: instructions_file on HiveFlow.run()**

- **FR-001**: The top-level Python API (`HiveFlow.run()`) MUST accept an optional `instructions_file` parameter that specifies a path to a text file containing workflow instructions.
- **FR-002**: When `instructions_file` is provided, the system MUST read the file as UTF-8 and use its content verbatim as the task string, without chunking or document-loader processing.
- **FR-003**: Providing both a non-empty `task` and `instructions_file` MUST raise an error indicating mutual exclusivity.
- **FR-004**: The system MUST accept any text-based file format for instructions (`.txt`, `.md`, `.rst`, etc.).

**Enhancement 2: load_from_bytes() on DocumentLoaderPlugin**

- **FR-005**: The document loader base class MUST provide a `load_from_bytes(data, filename)` method that accepts raw bytes and an original filename, returning a parsed Document.
- **FR-006**: The default implementation MUST write bytes to a temporary file, delegate to `load()`, and clean up the temporary file afterward — ensuring backward compatibility for existing loaders.
- **FR-007**: Loader implementations MAY override `load_from_bytes()` for direct byte-stream processing without temporary files.
- **FR-008**: The `DocumentPipeline` MUST be able to use `load_from_bytes()` when processing in-memory document content (e.g., from API uploads).

**Enhancement 3: summary Document Mode (LLM-based)**

- **FR-009**: When an agent's `document_mode` is set to `"summary"`, the system MUST generate an LLM-based summary of each document's content and provide the summary as a single chunk to the agent.
- **FR-010**: Document summaries MUST be cached in workflow state so that the same document is not re-summarized for multiple agents within the same workflow run.
- **FR-011**: The summary generation MUST use the configured Fast LLM tier model.
- **FR-012**: If no LLM provider is available, summary mode MUST fall back to `metadata_only` with a warning log.
- **FR-013**: Summaries MUST respect the configured maximum summary length (e.g., `MAX_SUMMARY_LENGTH` tokens).

**Enhancement 4: Prompt Template Variables for Documents**

- **FR-014**: The system MUST register document metadata variables (`$document_count`, `$document_names`, `$document_summary`) for prompt template resolution when documents are loaded into state.
- **FR-015**: Document template variables MUST resolve to sensible defaults when no documents are loaded (count=0, names and summary as empty strings).
- **FR-016**: Document template variables MUST be purely additive — templates that don't reference them are unaffected.

### Key Entities

- **Document**: A parsed representation of user-supplied input content, consisting of metadata (name, format, size) and a list of text chunks. Loaded by format-specific loader plugins.
- **Document Summary**: An LLM-generated condensed version of a document's content, cached per-document per-workflow-run. Used when agents request `document_mode="summary"`.
- **Instructions File**: A text file containing workflow instructions, read verbatim as the task string. Not processed through the document loader pipeline.

## Assumptions

- The existing `HiveFlow.run()` method signature can be extended with an additional optional parameter without breaking existing callers.
- The `DocumentLoaderPlugin` base class can be extended with a non-abstract method (`load_from_bytes()`) without breaking existing third-party loader implementations.
- The `FAST_LLM` tier is the appropriate model for summary generation (cheap and fast).
- Summary caching uses the workflow state dictionary (keyed by document name) — no external cache storage needed.
- The prompt template variable system (from feature 008) supports flat `$variable` substitution, which is sufficient for document metadata variables.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Python API users can load workflow instructions from a file with a single parameter, without manually reading the file or interacting with the workflow engine directly.
- **SC-002**: API/serverless integrations can load documents from byte streams without manual temporary file management.
- **SC-003**: Agents using `document_mode="summary"` receive condensed document summaries that reduce token usage by at least 70% compared to full document content, while preserving key information.
- **SC-004**: Repeated summary requests for the same document within a workflow run incur zero additional LLM calls due to caching.
- **SC-005**: Prompt templates can dynamically reference document count, names, and summary without hardcoding values.
- **SC-006**: All four enhancements are backward compatible — existing workflows, loaders, and templates continue to work without modification.
