# Feature Specification: Document Input Pipeline

**Feature Branch**: `001-document-input`
**Created**: 2026-02-18
**Status**: Draft
**Input**: User description: "Document Input Pipeline — first-class mechanism for feeding user-supplied documents into workflows"

## Clarifications

### Session 2026-02-18

- Q: How are documents identified when two files share the same basename? → A: Use full relative path as document name (e.g., `reports/summary.txt`). Per-agent scoping references the relative path, not just the basename.
- Q: What file path security restrictions apply? → A: Restrict file paths to the working directory or a configurable allowed-paths list. API uploads are restricted to a designated upload directory. Symlinks and path traversal sequences are rejected.
- Q: What is the default maximum total document size? → A: 50 MB (configurable). Loads exceeding this limit are rejected before processing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Load Documents by File Path (Priority: P1)

A user wants to run a workflow that processes one or more local files.
They pass file paths when invoking a workflow — either through the
SDK, CLI, or API — and the framework automatically loads, parses, and
chunks the files before the first agent executes. The user does not
need to understand the internal loading pipeline; they simply point at
files and get results.

**Why this priority**: This is the foundational capability. Without
file-path-based loading wired into the engine, no other document
feature (scoping, retrieval, extended formats) can function. It also
delivers immediate value: users can process local files today.

**Independent Test**: A user can invoke a single-agent workflow with a
text file, and the agent receives the file content in its context
without additional setup.

**Acceptance Scenarios**:

1. **Given** a workflow template and a local `.txt` file, **When** the
   user passes the file path via the `documents` parameter, **Then**
   the agent receives the file content split into chunks in its
   context, and the state contains a `documents` key with correct
   metadata (name, format, size, chunk count, token estimate).
2. **Given** multiple files of different supported formats, **When**
   the user passes all paths in a single invocation, **Then** every
   file is loaded, chunked, and made available in state with a
   `document_summary` describing all loaded documents.
3. **Given** inline content (a dictionary with `name` and `content`
   keys), **When** the user passes it in the documents list alongside
   file paths, **Then** both inline content and file-based content are
   loaded and accessible in state.
4. **Given** a file whose total token count exceeds the configured
   context budget, **When** the document is loaded, **Then** the
   framework applies the compression pipeline automatically and logs a
   message indicating compression was applied.
5. **Given** a non-existent file path, **When** the user includes it
   in the documents list, **Then** the framework raises a clear error
   identifying the missing file before any agent executes.

---

### User Story 2 — Load Instructions from a File (Priority: P1)

A user has a complex, multi-paragraph prompt that is unwieldy as an
inline string. They want to author the prompt in a text editor and
reference it by file path at execution time. The framework reads the
file and uses its content as the instructions string.

**Why this priority**: Addresses a real usability gap — long prompts
with formatting, examples, or step-by-step instructions are painful
to pass inline. This is tightly coupled to the core run interface and
should ship alongside document loading.

**Independent Test**: A user can invoke a workflow with
`--instructions-file ./prompt.md` (CLI) or
`instructions_file="./prompt.md"` (SDK) and the agent receives the
file's content as the task instructions.

**Acceptance Scenarios**:

1. **Given** a text file containing multi-paragraph instructions,
   **When** the user passes it via `instructions_file`, **Then** the
   file content is read as UTF-8 and assigned to `state["task"]`
   verbatim.
2. **Given** both `instructions` and `instructions_file` are provided,
   **When** the user invokes the workflow, **Then** the system raises
   an error stating they are mutually exclusive.
3. **Given** a CLI invocation with `--instructions -`, **When** the
   user pipes content from stdin, **Then** the piped content becomes
   the instructions string.
4. **Given** both `--instructions -` and `--doc -` in the same CLI
   invocation, **When** the user runs the command, **Then** the system
   raises an error because stdin cannot be consumed twice.

---

### User Story 3 — Per-Agent Document Scoping (Priority: P2)

In a multi-agent workflow with multiple loaded documents, a workflow
designer wants to control which documents each agent sees. A
summarizer agent should receive the full transcript; a fact-checker
should receive only relevant chunks; an editor should receive no
source documents at all. This is configured declaratively in the team
template, not in code.

**Why this priority**: Prevents context pollution in multi-agent
workflows, improving output quality and reducing token waste. Depends
on P1 loading being operational.

**Independent Test**: A three-agent workflow can be configured where
Agent A sees document X in full, Agent B sees only relevant chunks of
document X, and Agent C sees no documents — and each agent's context
confirms the expected scoping.

**Acceptance Scenarios**:

1. **Given** a team config where an agent specifies
   `"documents": ["transcript.txt"], "document_mode": "full"`,
   **When** the agent executes, **Then** the agent's context includes
   the entire content of `transcript.txt`.
2. **Given** an agent with `"document_mode": "relevant_chunks"` and an
   embedding provider configured, **When** the agent executes,
   **Then** only chunks semantically similar to the agent's task are
   included in context.
3. **Given** an agent with `"document_mode": "summary"`, **When** the
   agent executes, **Then** the agent receives a pre-generated summary
   of the referenced documents, not full content.
4. **Given** an agent with `"document_mode": "metadata_only"`,
   **When** the agent executes, **Then** the agent receives only
   document name, format, size, and chunk count — no content.
5. **Given** an agent with `"documents": []` or `documents` omitted,
   **When** the agent executes, **Then** no document content is
   injected into the agent's context.
6. **Given** an agent with `"max_document_tokens": 3000`, **When**
   document content exceeds 3000 tokens, **Then** content is truncated
   or compressed to fit the per-agent budget.

---

### User Story 4 — On-Demand Document Retrieval Tool (Priority: P3)

A tool-using agent in a workflow needs to look up specific content
from loaded documents during its reasoning process, rather than having
all content pre-injected. A document retrieval tool is registered as a
standard tool plugin, and the agent calls it on demand — searching by
document name, semantic query, or chunk index.

**Why this priority**: Most flexible access pattern, but only useful
for `tool_user` agents. Depends on P1 loading and provides an
alternative to P2 scoping for dynamic retrieval.

**Independent Test**: A `tool_user` agent can call the document
retrieval tool mid-execution to fetch specific chunks from a loaded
document and use them in its response.

**Acceptance Scenarios**:

1. **Given** a `tool_user` agent with `"document_retriever"` in its
   tool list and documents loaded in state, **When** the agent calls
   the tool with `document_name: "transcript.txt"`, **Then** the tool
   returns all chunks of that document.
2. **Given** a semantic query parameter, **When** the agent calls the
   retriever with `query: "main takeaways"`, **Then** the tool returns
   chunks ranked by relevance to the query.
3. **Given** specific chunk indices, **When** the agent requests
   `chunk_indices: [0, 2]`, **Then** only those chunks are returned.
4. **Given** a `max_tokens` parameter, **When** the returned content
   would exceed that limit, **Then** the result is truncated to fit.
5. **Given** no documents are loaded in state, **When** the agent
   calls the retriever, **Then** the tool returns an empty result with
   a descriptive message.

---

### User Story 5 — Extended Document Format Support (Priority: P2)

Users need to process documents beyond plain text — PDF reports, Word
documents, PowerPoint presentations, Excel spreadsheets, Markdown
files, HTML pages, JSON data, and XML files. Each format-specific
loader is a plugin that follows the existing `DocumentLoaderPlugin`
protocol.

**Why this priority**: Broadens the user base significantly. Most
real-world documents are not plain text. This is a parallel workstream
to P2 scoping — each new loader is independently useful once P1
loading works.

**Independent Test**: A user can pass a `.pdf` file (or `.docx`,
`.pptx`, `.xlsx`, `.md`, `.html`, `.json`, `.xml`) as a document to a
workflow and the agent receives the parsed content.

**Acceptance Scenarios**:

1. **Given** a `.md` file, **When** it is loaded, **Then** headings
   are used as chunk boundaries, preserving document structure.
2. **Given** a `.pdf` file, **When** it is loaded, **Then** text is
   extracted with page numbers included as metadata.
3. **Given** a `.docx` file, **When** it is loaded, **Then**
   paragraphs and headings are extracted and chunked.
4. **Given** a `.pptx` file, **When** it is loaded, **Then** content
   is extracted slide-by-slide, including speaker notes.
5. **Given** a `.xlsx` file, **When** it is loaded, **Then** content
   is extracted sheet-by-sheet and converted to a text representation.
6. **Given** a `.html` file, **When** it is loaded, **Then** main
   content is extracted and navigation/advertisements are stripped.
7. **Given** a `.json` file, **When** it is loaded, **Then** content
   is pretty-printed or extracted by path.
8. **Given** an unsupported file extension, **When** it is passed as a
   document, **Then** the system raises a clear error naming the
   unsupported format and listing supported formats.

---

### User Story 6 — Document Upload via API (Priority: P3)

An integrator using HiveFlow's server mode wants to upload documents
alongside workflow execution requests. They submit files via multipart
form upload, and the server feeds them through the same loading
pipeline as the SDK and CLI.

**Why this priority**: Server mode is a secondary interface. The API
endpoint extends the same pipeline built for P1, making it additive
rather than foundational.

**Independent Test**: An HTTP client can POST a multipart request with
file attachments to the workflow endpoint and receive results that
reference the uploaded documents.

**Acceptance Scenarios**:

1. **Given** a multipart POST to the workflow endpoint with file
   attachments, **When** the request is processed, **Then** the
   attached files are loaded through the document pipeline and made
   available to agents.
2. **Given** a running workflow, **When** an integrator POSTs
   documents to the workflow's document endpoint, **Then** documents
   are added to the workflow's state.
3. **Given** a GET request to the workflow's documents endpoint,
   **When** documents have been loaded, **Then** the response lists
   all loaded documents with their metadata.
4. **Given** a GET request for a specific document by name, **When**
   the document exists, **Then** the response returns the document's
   chunks and content.

---

### Edge Cases

- What happens when a file path points to a binary file with no
  registered loader (e.g., `.exe`, `.zip`)? The system MUST raise an
  error identifying the unsupported format.
- What happens when a document loader plugin's dependency package is
  not installed (e.g., `pymupdf` for PDF)? The system MUST log a
  warning, skip registration of that loader, and raise a clear error
  if a user attempts to load that format.
- What happens when the total size of all documents exceeds available
  memory? The system MUST enforce a configurable maximum total
  document size (default: 50 MB) and reject loads that exceed it with
  an informative message before any processing begins.
- What happens when a file is empty (zero bytes)? The system MUST
  load it successfully with zero chunks and a zero token estimate.
- What happens when stdin is specified for both documents and
  instructions in the same CLI call? The system MUST reject the
  invocation with a clear error before attempting to read.
- What happens when a document name in per-agent scoping does not
  match any loaded document? The system MUST raise an error at
  workflow start, not mid-execution.
- What happens when `relevant_chunks` mode is used but no embedding
  provider is configured? The system MUST fall back to `full` mode and
  log a warning.
- What happens when two files share the same basename (e.g.,
  `./reports/summary.txt` and `./archive/summary.txt`)? The system
  MUST use the full relative path as the document `name`, ensuring
  uniqueness. Per-agent scoping references the relative path.
- What happens when a file path contains traversal sequences (e.g.,
  `../../etc/passwd`) or resolves to a symlink outside the working
  directory? The system MUST reject the path with an error before
  loading. Allowed paths are configurable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept file paths and inline content
  dictionaries in a `documents` parameter when invoking a workflow.
- **FR-002**: The system MUST automatically detect file format by
  extension and route to the appropriate document loader plugin.
- **FR-003**: The system MUST chunk loaded documents using the existing
  chunking utility when content exceeds the configured chunk size.
- **FR-004**: The system MUST populate the workflow state with a
  `documents` key containing structured metadata (name, format,
  size_bytes, chunks, chunk_count, total_tokens_estimate) for every
  loaded document.
- **FR-005**: The system MUST populate a `document_summary` key in
  state with a human-readable summary of all loaded documents.
- **FR-006**: The system MUST support loading instructions from a file
  via `instructions_file` (SDK) and `--instructions-file` (CLI),
  mutually exclusive with inline instructions.
- **FR-007**: The system MUST support reading instructions from stdin
  via `--instructions -` on the CLI.
- **FR-008**: The system MUST apply the existing context compression
  pipeline when total document content exceeds the configured context
  budget.
- **FR-009**: The system MUST support per-agent document scoping via
  `documents` and `document_mode` fields in agent definitions within
  team configs.
- **FR-010**: The system MUST support five document modes: `full`,
  `relevant_chunks`, `summary`, `metadata_only`, and `none`.
- **FR-011**: The system MUST support a per-agent
  `max_document_tokens` override for document context budgets.
- **FR-012**: The system MUST provide a `DocumentRetrieverTool` that
  allows tool-using agents to fetch document content on demand by
  name, semantic query, or chunk index.
- **FR-013**: The system MUST support document loader plugins for:
  `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.json`, `.xml`
  in addition to the existing `.txt`, `.csv`, `.tsv`.
- **FR-014**: The system MUST discover document loader plugins via the
  `hiveflow.document_loaders` entry point group.
- **FR-015**: The system MUST gracefully handle missing optional plugin
  dependencies by logging a warning and skipping registration.
- **FR-016**: The system MUST expose document upload and retrieval
  endpoints in server mode for multipart file uploads and document
  metadata queries.
- **FR-017**: The system MUST raise clear, actionable errors for:
  unsupported formats, missing files, mutual exclusivity violations,
  stdin conflicts, and unresolved document references in agent scoping.
- **FR-018**: The system MUST complete all document loading and
  validation before the first agent executes.
- **FR-019**: The system MUST validate that all file paths resolve
  within the working directory or a configurable allowed-paths list.
  Paths containing traversal sequences (e.g., `../`) or symlinks
  pointing outside allowed directories MUST be rejected with a clear
  error. API uploads MUST be written to a designated upload directory.
- **FR-020**: The system MUST enforce a configurable maximum total
  document size per workflow invocation (default: 50 MB). Loads
  exceeding this limit MUST be rejected with an informative error
  before any processing begins.

### Key Entities

- **Document**: A user-supplied file or inline content item. Key
  attributes: name (full relative path for file-based documents, or
  the user-provided name for inline content), format, size in bytes,
  raw content, chunks, chunk count, token estimate. The `name` field
  is the canonical identifier used in per-agent scoping.
- **DocumentChunk**: A segment of a document produced by the chunking
  utility. Key attributes: parent document name, index, text content,
  token estimate.
- **DocumentLoaderPlugin**: A format-specific parser that converts raw
  file content into document chunks. Attributes: supported extensions,
  load method, load-from-bytes method.
- **DocumentRetrieverTool**: A tool plugin that agents invoke at
  runtime to fetch document content from state. Parameters: document
  name, semantic query, chunk indices, max tokens.
- **DocumentMode**: A per-agent configuration value controlling how
  document content is delivered to the agent. Values: full,
  relevant_chunks, summary, metadata_only, none.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can pass up to 20 local files to a single workflow
  invocation and receive a result that references content from all
  loaded files.
- **SC-002**: A new user can process their first document-based
  workflow with only a template name, an instructions string, and a
  file path — no additional configuration required.
- **SC-003**: 100% of loaded documents have complete, accurate
  metadata (name, format, size, chunk count, token estimate) available
  in workflow state.
- **SC-004**: When total document content exceeds the context budget,
  compression is applied automatically and the user is notified — no
  silent truncation or data loss occurs without a log message.
- **SC-005**: In a multi-agent workflow, each agent receives only the
  document content prescribed by its scoping configuration — no
  context pollution across agents.
- **SC-006**: All supported file formats (.txt, .csv, .tsv, .md, .pdf,
  .docx, .pptx, .xlsx, .html, .json, .xml) are loadable through the
  same user-facing interface with no format-specific user steps.
- **SC-007**: Error messages for unsupported formats, missing files,
  and configuration conflicts identify the specific problem and
  suggest a resolution in every case.
- **SC-008**: File-based instructions (`instructions_file` /
  `--instructions-file`) work identically to inline instructions from
  the agent's perspective — no behavioral difference downstream.

## Assumptions

- The existing `DocumentLoaderPlugin` protocol, `chunk_text()` utility,
  and context compression pipeline are stable and will not undergo
  breaking changes during this feature's development.
- The existing `PlainTextLoader` for `.txt`, `.csv`, `.tsv` is
  correct and serves as the reference implementation for new loaders.
- The `initial_state` dictionary mechanism in `WorkflowEngine` is the
  primary injection point for pre-workflow data and will continue to
  be supported.
- Embedding providers may or may not be configured in a given
  deployment; the `relevant_chunks` document mode gracefully degrades
  when no provider is available.
- Server mode (FastAPI) is operational and the existing endpoint
  structure supports extension with multipart upload handling.
- File encoding is UTF-8 unless the format-specific loader handles
  encoding detection internally (e.g., PDF binary parsing).

## Scope Boundaries

**In scope**:
- File-path and inline-content document loading
- Instructions-from-file support
- Chunking and compression integration
- Per-agent document scoping configuration
- On-demand document retrieval tool
- Loader plugins for 9 additional file formats
- Server-mode document upload endpoints
- CLI `--doc` and `--instructions-file` arguments

**Out of scope**:
- Cloud or remote document sources (S3, URLs, Google Drive) — covered
  by a separate feature
- Real-time document change watching / hot-reload
- Document version tracking or diffing
- OCR for image-based PDFs (text extraction only)
- Authentication or access control on document endpoints
- Custom user-defined document loader plugins (the plugin protocol
  exists; documenting how end-users author plugins is a separate
  concern)
