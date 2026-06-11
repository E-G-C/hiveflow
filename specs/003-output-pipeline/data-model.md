# Data Model: Output Pipeline Architecture

**Feature**: 003-output-pipeline
**Date**: 2026-02-20

## Entity Relationship Overview

```
WorkflowResult ──assembles──▶ ResultPayload
                                  │
                                  ├── sections: list[PayloadSection]
                                  ├── references: list[Citation]   (existing)
                                  ├── actions: list[ActionRecord]
                                  ├── cost_summary: WorkflowCostReport (existing)
                                  └── metadata: dict[str, Any]
                                        │
ResultPayload ──dispatched to──▶ PublisherRegistry
                                  │
                                  ├── MarkdownPublisher
                                  ├── JSONPublisher
                                  ├── HTMLPublisher
                                  ├── PDFPublisher
                                  └── DOCXPublisher
                                        │
                                        ▼
                                  LayoutTemplate (resolves section order)
```

## Entities

### ResultPayload (NEW)

The structured output of a completed workflow, assembled from
`WorkflowResult` and associated tracking data.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `str` | Yes | Workflow title (from task description or team config) |
| `content` | `str` | Yes | Full assembled text output (concatenated agent outputs) |
| `sections` | `list[PayloadSection]` | Yes | Ordered named content blocks |
| `metadata` | `dict[str, Any]` | Yes | Arbitrary KV: date, workflow_id, run_duration, template_name |
| `references` | `list[Citation]` | Yes | Cited sources (reuses existing `Citation` dataclass); empty list if none |
| `actions` | `list[ActionRecord]` | Yes | Real-world actions taken; empty list if none |
| `cost_summary` | `WorkflowCostReport` | Yes | Per-agent and total token/cost figures (reuses existing dataclass) |
| `step_results` | `list[StepResult]` | Yes | Per-step execution details (reuses existing dataclass) |

**Identity**: Unique per workflow execution. No persistent ID — ephemeral object.
**Lifecycle**: Created once after workflow completes; immutable after creation.

### PayloadSection (NEW)

A named block of content within a `ResultPayload`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `section_id` | `str` | Yes | Machine-readable identifier (e.g., `"executive_summary"`, `"findings"`) |
| `title` | `str` | Yes | Human-readable section heading |
| `content` | `str` | Yes | Markdown content for this section |
| `agent_id` | `str \| None` | No | The agent that produced this section (if attributable) |
| `order` | `int` | Yes | Sort position within the payload |

**Identity**: Unique by `section_id` within a `ResultPayload`.

### ActionRecord (NEW)

A real-world action taken during workflow execution.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action_id` | `str` | Yes | Unique identifier |
| `action_type` | `str` | Yes | Category (e.g., `"email"`, `"api_call"`, `"file_write"`) |
| `description` | `str` | Yes | Human-readable description of what was done |
| `status` | `str` | Yes | `"completed"`, `"failed"`, `"pending"`, `"approved"`, `"rejected"` |
| `agent_id` | `str` | Yes | Agent that initiated the action |
| `timestamp` | `float` | Yes | Unix timestamp of execution |
| `metadata` | `dict[str, Any]` | No | Action-specific details |

**Identity**: Unique by `action_id`.
**Lifecycle**: Created during workflow execution; immutable after workflow completes.

### LayoutTemplate (NEW)

Defines document structure for published output.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `str` | Yes | Template identifier (e.g., `"default"`, `"executive-brief"`) |
| `description` | `str` | No | Human-readable description |
| `sections` | `list[LayoutSection]` | Yes | Ordered section definitions |

**Identity**: Unique by `name`.
**Storage**: YAML files in `hiveflow/templates/layouts/`.
**Resolution**: By name from a layout directory; falls back to `"default"`.

### LayoutSection (NEW)

A section definition within a `LayoutTemplate`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | Yes | Section identifier (must match a `PayloadSection.section_id` or special key) |
| `source` | `str` | Yes | Dot-path to the payload field (e.g., `"content"`, `"metadata.title"`, `"auto"` for generated) |
| `required` | `bool` | Yes | If true and content is empty, emit warning; if false and empty, omit section |
| `heading` | `str \| None` | No | Override heading text (defaults to section title from payload) |

### PublishConfig (NEW)

User-facing configuration block within a team config.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `formats` | `list[str]` | No | `[]` | Publisher IDs to invoke (e.g., `["markdown", "pdf"]`) |
| `layout` | `str` | No | `"default"` | Named layout template |
| `style` | `str \| None` | No | `None` | Style name for PDF/HTML (CSS or LaTeX template) |
| `output_dir` | `str` | No | `"./output"` | Target directory for output files |
| `filename` | `str` | No | `"output"` | Base filename (without extension) |

**Validation**: `formats` entries must correspond to registered publisher IDs.
`layout` must resolve to an existing template.

### CompletionCallback (TYPE ALIAS)

```python
CompletionCallback = Callable[[ResultPayload], None] | Callable[[ResultPayload], Awaitable[None]]
```

Not a data model entity — a type alias for registered callables.

## Reused Existing Entities

These entities already exist in the codebase and are referenced by
`ResultPayload` without modification:

| Entity | Module | Used as |
|--------|--------|---------|
| `Citation` | `hiveflow.core.citations` | `ResultPayload.references` items |
| `WorkflowCostReport` | `hiveflow.core.cost` | `ResultPayload.cost_summary` |
| `AgentCostSummary` | `hiveflow.core.cost` | Inside `WorkflowCostReport.agent_summaries` |
| `StepResult` | `hiveflow.core.workflow` | `ResultPayload.step_results` items |
| `WorkflowResult` | `hiveflow.core.workflow` | Source data for `ResultPayload` assembly |

## State Transitions

### ResultPayload Lifecycle

```
WorkflowEngine.execute() completes
    │
    ▼
WorkflowResult returned
    │
    ▼
ResultPayload.from_workflow_result(result, cost_tracker, citation_manager)
    │     ↳ Assembles content, sections, references, actions, cost_summary
    ▼
ResultPayload (immutable)
    │
    ├──▶ PublisherRegistry.publish_all(payload, config)
    │       ├── MarkdownPublisher → .md file
    │       ├── JSONPublisher → .json file
    │       ├── HTMLPublisher → .html file
    │       ├── PDFPublisher → .pdf file
    │       └── DOCXPublisher → .docx file
    │
    └──▶ CompletionCallbacks invoked with payload
```

### Publisher Dispatch Flow

```
publish_all(payload, config)
    │
    ├── De-duplicate formats list
    ├── Resolve layout template by name
    │
    ▼ for each format:
    ├── Look up publisher in registry
    ├── If not found → log warning, skip
    ├── Call publisher.publish_payload(payload, config)
    │     ├── Apply layout template to order sections
    │     ├── Render content in target format
    │     └── Write to output_dir/filename.ext
    ├── On success → log output.publish.complete
    └── On error → log output.publish.error, continue to next
```
