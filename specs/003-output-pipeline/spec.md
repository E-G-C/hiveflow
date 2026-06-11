# Feature Specification: Output Pipeline Architecture

**Feature Branch**: `003-output-pipeline`
**Created**: 2026-02-20
**Status**: Draft
**Input**: User description: "Output Pipeline Architecture — decoupled export with publisher plugins for rendering workflow result payloads to multiple formats (Markdown, PDF, DOCX, HTML, JSON)"

## Clarifications

### Session 2026-02-20

- Q: DOCX conversion strategy — htmldocx is abandoned (repo deleted, no release since 2021). What replaces it? → A: Use pypandoc (wraps pandoc binary) for best-fidelity Markdown → DOCX conversion. Accepts the system dependency trade-off (pandoc binary ~100 MB) for superior output quality.
- Q: PDF rendering library — md2pdf/WeasyPrint requires system libs (Pango/GLib); alternatives? → A: Use pypandoc for PDF too, reusing the pandoc binary from DOCX. Consolidates system deps to a single binary (pandoc + LaTeX engine for styled PDFs). Replaces md2pdf/WeasyPrint.
- Q: Pandoc installation strategy — how should the pandoc system binary be managed for framework users? → A: Bundle via `pypandoc_binary` package (~100 MB) so installation is a single `uv add hiveflow[publishers]` with zero system setup.
- Q: Markdown parser consolidation — keep mistune for HTML or use pypandoc for all formats (HTML, PDF, DOCX)? → A: Use pypandoc for all three. Single conversion engine simplifies the architecture. Users who only need Markdown + JSON publishers don't need pandoc (those are zero-dep).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Publish Workflow Results as Markdown (Priority: P1)

A developer runs a multi-agent workflow that produces a text result. After the
workflow completes, they want to export the result as a properly formatted
Markdown file — including a title, date, table of contents (when headings are
present), section content, references, and an appendix with cost/token metadata.
They call a single publish method (or CLI flag) and receive a `.md` file on disk.

**Why this priority**: Markdown is the lowest-friction output format. It requires
no third-party rendering libraries, exercises the full result-payload → layout →
publisher pipeline end-to-end, and validates the plugin interface that every
other publisher builds on. Shipping this alone delivers immediate value: users
get structured, human-readable output files from any workflow.

**Independent Test**: Run a workflow with two agents, pass the result to the
Markdown publisher with default layout, and verify the `.md` file contains the
expected sections in order with correct metadata.

**Acceptance Scenarios**:

1. **Given** a completed workflow result with content and metadata, **When** the
   user calls `publish("markdown", result, output_dir="./output")`, **Then** a
   `.md` file is created in `./output/` containing a title, date, body content,
   references section, and an appendix with token/cost summary.
2. **Given** a result whose content contains level-2 headings, **When** the
   default layout includes a table of contents, **Then** the generated Markdown
   has a "Table of Contents" section with anchor links to each heading.
3. **Given** a workflow result with `references` in its metadata, **When**
   published as Markdown, **Then** the references appear as a numbered list at
   the end of the document body.
4. **Given** an output directory that does not exist, **When** the user triggers
   publish, **Then** the directory is created automatically and the file is
   written without error.
5. **Given** a workflow result with no content (empty string), **When** the user
   publishes it, **Then** the system produces a valid file containing only
   metadata and frontmatter sections (no validation error is raised; an empty
   result is not an error condition).

---

### User Story 2 — Publish Results in Multiple Formats at Once (Priority: P1)

A team lead configures a workflow to automatically export results in PDF, DOCX,
and Markdown after every run. They set `formats: ["pdf", "docx", "markdown"]` in
the team configuration. When the workflow finishes, the system produces all three
files in the specified output directory without additional user action.

**Why this priority**: Multi-format publishing is the core value proposition of
the output pipeline — the entire decoupled architecture exists to support it. It
validates the Publisher Registry, parallel dispatch, and per-publisher error
isolation.

**Independent Test**: Configure a workflow with three output formats, run it, and
verify that exactly three files are created with the correct extensions and that
a failure in one publisher does not prevent the others from completing.

**Acceptance Scenarios**:

1. **Given** a team config with `publish.formats: ["pdf", "docx", "markdown"]`,
   **When** a workflow completes, **Then** three files appear in
   `publish.output_dir` with extensions `.pdf`, `.docx`, and `.md`.
2. **Given** a team config requesting format `"pdf"` but the PDF publisher
   is not installed (missing optional dependency), **When** the workflow
   completes, **Then** the system logs a warning for the missing publisher and
   still produces the other requested formats successfully.
3. **Given** a list of formats that includes a duplicate (e.g.,
   `["markdown", "markdown"]`), **When** published, **Then** the system
   de-duplicates and produces only one Markdown file.

---

### User Story 3 — Construct a Structured Result Payload (Priority: P1)

A developer using the SDK wants to programmatically inspect the structured
output of a workflow — the final content, per-agent summaries, tool calls,
action log, citations, and cost breakdown — without parsing a rendered document.
They access a `ResultPayload` object returned by the engine (or retrieve it via
the API) and iterate over its structured fields.

**Why this priority**: The result payload is the input to every publisher. Until
it exists as a well-defined data model, no publisher can operate. It also serves
SDK and API consumers who never render documents at all — they consume the
payload directly.

**Independent Test**: Run a workflow, access the returned `ResultPayload`, and
assert that it contains the expected fields (title, content, sections,
references, actions, cost summary) with correct types.

**Acceptance Scenarios**:

1. **Given** a completed workflow, **When** the engine returns its result,
   **Then** the result includes a `ResultPayload` with fields: `title`,
   `content`, `sections`, `metadata`, `references`, `actions`, and
   `cost_summary`.
2. **Given** a workflow with three agents, **When** the payload is inspected,
   **Then** `cost_summary` contains per-agent token counts and an overall total.
3. **Given** a workflow that used citations, **When** the payload is inspected,
   **Then** `references` contains the cited sources with titles and URLs.
4. **Given** a workflow whose agents produced no actions, **When** the payload is
   inspected, **Then** `actions` is an empty list (not `None`).

---

### User Story 4 — Apply a Custom Layout Template (Priority: P2)

A user wants their published reports to follow a specific document structure —
for example, starting with an executive summary, followed by findings grouped by
topic, then a risk matrix, and ending with an appendix. They create a layout
template that defines section order and optional/required sections, reference it
in their team config, and the publisher uses that layout instead of the default.

**Why this priority**: Layout templates differentiate generic "dump text to file"
from structured, professional-quality reports. This is essential for enterprise
and team use but is additive — users can get value from default layouts without
it.

**Independent Test**: Create a custom layout template that reorders sections and
omits the table of contents, publish a result, and verify the output matches the
custom section order with no TOC.

**Acceptance Scenarios**:

1. **Given** a custom layout template that specifies sections
   `[executive_summary, findings, appendix]`, **When** a result is published,
   **Then** the output document contains exactly those three sections in order.
2. **Given** a layout template that marks `references` as optional and the result
   has no references, **When** published, **Then** the references section is
   omitted entirely from the output.
3. **Given** a team config with `publish.layout: "executive-brief"`, **When** the
   publisher looks up the layout, **Then** it resolves the named template from
   the registered layout directory.
4. **Given** an invalid layout template name that does not exist, **When** the
   user attempts to publish, **Then** the system raises a clear error identifying
   the unknown layout name and listing available layouts.

---

### User Story 5 — Publish Results as PDF with Styled Layout (Priority: P2)

A user wants a polished, print-ready PDF of their workflow results. The PDF
should use consistent typography, proper page breaks between major sections, and
support the same layout template system as other formats.

**Why this priority**: PDF is the most requested format for sharing results with
non-technical stakeholders and for archival. It relies on the layout system from
User Story 4 and demonstrates that the publisher interface supports both text and
binary output.

**Independent Test**: Publish a workflow result as PDF and verify the output
is a valid PDF file whose text content matches the expected sections.

**Acceptance Scenarios**:

1. **Given** a result payload and the default layout, **When** published as PDF,
   **Then** a valid `.pdf` file is created that contains the title, date, and
   body content.
2. **Given** a custom CSS style specified in config, **When** published as PDF,
   **Then** the PDF reflects the custom styles (e.g., font family, heading size).
3. **Given** a result with very long content (50+ pages equivalent), **When**
   published as PDF, **Then** the PDF is generated without timeout or memory
   errors.

---

### User Story 6 — Publish Results as DOCX (Priority: P2)

A user needs their results in a Word-compatible format for editing and
distribution within an organization that uses Microsoft Office. The exported DOCX
should preserve headings, lists, and basic formatting from the Markdown content.

**Why this priority**: DOCX is required for enterprise collaboration. It
exercises the Markdown-to-HTML-to-DOCX conversion chain and validates binary
output handling.

**Independent Test**: Publish a result as DOCX, open the file, and verify that
headings, lists, and paragraphs are correctly formatted.

**Acceptance Scenarios**:

1. **Given** a result payload, **When** published as DOCX, **Then** a valid
   `.docx` file is created that can be opened in any word processor.
2. **Given** content with Markdown headings (`##`, `###`), **When** published as
   DOCX, **Then** the headings are converted to Word heading styles.
3. **Given** content with inline code and code blocks, **When** published as
   DOCX, **Then** the code is rendered in a monospace font.

---

### User Story 7 — Register a Custom Third-Party Publisher (Priority: P3)

A plugin author wants to add a new output format (e.g., LaTeX, Confluence Wiki,
Slack message) without modifying the core framework. They implement the publisher
protocol, register it via a Python entry point, and it becomes available
alongside built-in publishers.

**Why this priority**: Extensibility is core to HiveFlow's plugin architecture
but is additive — users get value from built-in publishers first. This validates
that the publisher interface is a true plugin contract, not just an internal
abstraction.

**Independent Test**: Create a minimal publisher plugin in a separate package,
install it, and verify it appears in the publisher registry and can be invoked by
format name.

**Acceptance Scenarios**:

1. **Given** a third-party package that implements `PublisherPlugin` and
   registers via the `hiveflow.publishers` entry point, **When** the publisher
   registry is initialized, **Then** the new publisher appears in the list of
   available formats.
2. **Given** a registered custom publisher with `publisher_id = "latex"`,
   **When** the user includes `"latex"` in `publish.formats`, **Then** the
   publisher's `publish()` method is called with the result payload.
3. **Given** a custom publisher whose `publish()` raises an exception, **When**
   invoked as part of a multi-format publish, **Then** the error is logged and
   other publishers are not affected.

---

### User Story 8 — Receive Results via Callback Hook (Priority: P3)

A developer building an application on top of HiveFlow wants to receive the
result payload programmatically when a workflow completes — for example, to
forward it to an S3 bucket, send an email, post to Slack, or update a Jira
ticket. They register a callback function that is invoked with the result payload
on workflow completion.

**Why this priority**: Callbacks decouple the framework from specific delivery
mechanisms. This is essential for automation pipelines but is additive on top of
the file-based publishers.

**Independent Test**: Register a callback that appends the payload to a list, run
a workflow, and verify the callback was invoked with the correct payload.

**Acceptance Scenarios**:

1. **Given** a registered callback function, **When** a workflow completes,
   **Then** the callback is invoked with the `ResultPayload` object.
2. **Given** multiple registered callbacks, **When** a workflow completes,
   **Then** all callbacks are invoked in registration order.
3. **Given** a callback that raises an exception, **When** invoked, **Then** the
   error is logged and subsequent callbacks still execute.
4. **Given** an async callback function, **When** registered and invoked,
   **Then** it is awaited correctly.

---

### Edge Cases

- What happens when the output directory path contains special characters or
  spaces? → The publisher normalizes the path and creates any missing
  intermediate directories.
- What happens when a publisher writes a file that already exists at the target
  path? → The file is overwritten. A future enhancement may add a
  `overwrite: bool` config option.
- What happens when disk space is insufficient to write the output? → The
  publisher raises an `IOError` with a descriptive message.
- What happens when a layout template references a section that does not exist in
  the result payload? → The section is silently omitted (unless marked as
  required in the layout, in which case a warning is logged).
- What happens when publish is called with an empty formats list? → No files are
  created; the call returns an empty list of paths.
- What happens when the result payload content is extremely large (> 100 MB of
  text)? → The publisher operates in a streaming fashion where possible; for
  formats that require in-memory rendering (PDF, DOCX), the system logs a
  warning if content exceeds a configurable threshold.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST define a `ResultPayload` data model containing:
  `title`, `content` (full assembled text), `sections` (ordered list of named
  content blocks), `metadata` (arbitrary key-value pairs including date and
  workflow ID), `references` (list of cited sources), `actions` (list of
  real-world actions taken), and `cost_summary` (per-agent and total token
  counts and estimated cost).
- **FR-002**: The workflow engine MUST assemble a `ResultPayload` from the
  completed workflow state, including outputs from all agents, aggregated
  citations, and cost tracking data already captured by the engine.
- **FR-003**: The system MUST provide a `PublisherPlugin` protocol with
  properties `publisher_id`, `description`, `output_extension`, and two async
  methods: `publish(content, output_path, metadata)` (legacy string API
  returning `Path`) and `publish_payload(payload, output_path, layout, config)`
  (payload-aware API returning `Path`, with default fallback to `publish`).
- **FR-004**: The system MUST provide a `PublisherRegistry` that discovers
  publisher plugins via Python entry points (`hiveflow.publishers` group) and
  an optional drop-in directory.
- **FR-005**: The system MUST include built-in publishers for Markdown, JSON,
  HTML, PDF, and DOCX formats.
- **FR-006**: The Markdown publisher MUST produce a well-structured `.md` file
  following the active layout template, with YAML frontmatter for metadata.
- **FR-007**: The JSON publisher MUST serialize the full `ResultPayload` to a
  `.json` file preserving all fields.
- **FR-008**: The HTML publisher MUST convert Markdown content to HTML using
  pypandoc (pandoc) for conversion and a Jinja2 template for styling and layout.
- **FR-009**: The PDF publisher MUST convert content to a styled `.pdf` file
  using pypandoc (pandoc + LaTeX engine), accepting an optional LaTeX template
  or CSS stylesheet for customization.
- **FR-010**: The DOCX publisher MUST convert content to a `.docx` file with
  proper heading levels, lists, and inline formatting, using pypandoc (pandoc)
  for conversion.
- **FR-011**: The registry MUST support publishing to multiple formats in a
  single call, isolating failures so that one publisher's error does not block
  others.
- **FR-012**: The system MUST provide a default layout template defining section
  order: title, date, table of contents, executive summary / introduction,
  section content, actions taken, conclusion / next steps, references, appendix
  (cost/token breakdown).
- **FR-013**: Users MUST be able to define custom layout templates and reference
  them by name in team configuration (`publish.layout`).
- **FR-014**: Layout templates MUST support marking sections as optional or
  required; optional sections with no content are omitted from the output;
  required sections with no content emit a warning.
- **FR-015**: Team configuration MUST accept a `publish` block with keys:
  `formats` (list of publisher IDs), `layout` (template name, default:
  `"default"`), `style` (reserved for future CSS/LaTeX template support,
  default: `None`), `output_dir` (path, default: `"./output"`), and
  `filename` (base filename without extension, default: `"output"`).
- **FR-016**: The system MUST support registering completion callbacks that
  receive the `ResultPayload` when a workflow finishes.
- **FR-017**: Callback execution MUST be isolated — an exception in one callback
  does not prevent subsequent callbacks from running.
- **FR-018**: The system MUST support both synchronous and asynchronous
  callbacks.
- **FR-019**: All publisher operations MUST emit structured log events
  (`output.publish.start`, `output.publish.complete`, `output.publish.error`)
  with publisher ID, format, output path, and duration.
- **FR-020**: The existing `PublisherPlugin` base class and `PublisherRegistry`
  MUST be extended (not replaced) to support the new `ResultPayload`-based
  `publish` signature while maintaining backward compatibility with the current
  `content: str` signature.

### Key Entities

- **ResultPayload**: The structured output of a completed workflow. Contains the
  full assembled content, per-section breakdown, metadata (title, date, workflow
  ID, run duration), ordered list of references/citations, list of actions taken,
  and a cost summary with per-agent and total token/cost figures.
- **PublisherPlugin**: A plugin that renders a `ResultPayload` into a specific
  output format. Identified by `publisher_id` (e.g., `"pdf"`, `"docx"`). May
  produce text (`str`) or binary (`bytes`) output.
- **PublisherRegistry**: The discovery and dispatch layer. Loads publishers from
  entry points and drop-in directories. Supports multi-format publish in one
  call.
- **LayoutTemplate**: Defines the document structure for published output —
  which sections appear, in what order, and whether they are required or
  optional. Named templates are resolved from a template directory.
- **PublishConfig**: The user-facing configuration block within a team config.
  Specifies formats, layout, style, and output directory.
- **CompletionCallback**: A callable (sync or async) registered to receive the
  `ResultPayload` when a workflow finishes.

## Assumptions

- The existing `WorkflowResult` data class and cost tracking infrastructure
  provide sufficient data to populate the `ResultPayload`. No new data-collection
  mechanisms are needed inside the engine.
- PDF rendering will use `pypandoc` (wrapping the pandoc binary) with a LaTeX
  engine for styled output. This reuses the same pandoc binary required for DOCX,
  consolidating system dependencies. The `md2pdf`/WeasyPrint approach is
  explicitly rejected to avoid a second set of system-level libraries
  (Pango, GLib).
- The pandoc binary will be bundled via the `pypandoc_binary` package so that
  installing `hiveflow[publishers]` requires zero manual system setup. The
  `pypandoc_binary` package adds ~100 MB but eliminates user friction.
- DOCX rendering will use `pypandoc` (wrapping the pandoc binary) for
  best-fidelity Markdown → DOCX conversion. The abandoned `htmldocx` library
  and `python-docx` direct usage are explicitly rejected for this purpose.
- HTML rendering will use `pypandoc` for Markdown → HTML conversion and `jinja2`
  for templating/styling. This consolidates all document conversion (HTML, PDF,
  DOCX) onto a single engine (pandoc via pypandoc). The `mistune` library is no
  longer needed for the output pipeline. Users who only need the Markdown and
  JSON publishers do not require pandoc — those publishers have zero external
  dependencies.
- Layout templates will be authored as simple structured data (YAML or Python
  dataclass), not as Jinja2 templates. Jinja2 is used only for HTML publisher
  styling/layout wrapping.
- The existing `PublisherPlugin` signature (`content: str`) will continue to work
  alongside the new `ResultPayload`-based signature for backward compatibility.
- All document conversion (HTML, PDF, DOCX) is consolidated on pypandoc/pandoc.
  The `publishers` optional extra will depend on `pypandoc`, `pypandoc_binary`,
  and `jinja2`. The Markdown and JSON publishers remain zero-dependency.
  Libraries previously listed for this purpose (`md2pdf`, `htmldocx`, `mistune`)
  are replaced by pypandoc.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A workflow result can be exported to Markdown, JSON, HTML, PDF, and
  DOCX with a single configuration change (adding format names to the
  `publish.formats` list).
- **SC-002**: Publishing to all five built-in formats completes in under 10
  seconds for a typical result (< 50 pages of content).
- **SC-003**: A failure in one publisher (e.g., missing PDF dependency) does not
  prevent other publishers from completing — at least 4 of 5 formats are
  delivered.
- **SC-004**: A third-party publisher plugin can be installed and used without
  modifying any core framework code — the only requirement is implementing the
  protocol and registering an entry point.
- **SC-005**: The `ResultPayload` data model contains all information needed to
  reproduce any published document — no publisher needs to query the workflow
  engine or external state.
- **SC-006**: Custom layout templates can reorder, add, or remove document
  sections, and the output reflects the custom structure on first publish without
  code changes.
- **SC-007**: Completion callbacks are invoked within 1 second of workflow
  completion, reliably, even when individual callbacks fail.
