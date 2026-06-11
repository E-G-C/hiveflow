# SDK API Contract: Output Pipeline

**Feature**: 003-output-pipeline
**Date**: 2026-02-20

## ResultPayload

### Construction

```python
from hiveflow.core.result_payload import ResultPayload

# Automatic assembly from workflow result (primary path)
payload = ResultPayload.from_workflow_result(
    result=workflow_result,           # WorkflowResult from engine.execute()
    cost_report=cost_tracker.get_report(),  # WorkflowCostReport
    citations=citation_manager.get_all(),   # list[Citation]
    title="My Research Report",       # Optional override; defaults to state["task"]
)

# Direct construction (for testing or custom pipelines)
payload = ResultPayload(
    title="Custom Report",
    content="Full markdown content...",
    sections=[
        PayloadSection(section_id="intro", title="Introduction", content="...", order=0),
        PayloadSection(section_id="findings", title="Findings", content="...", order=1),
    ],
    metadata={"date": "2026-02-20", "workflow_id": "abc123"},
    references=[],
    actions=[],
    cost_summary=WorkflowCostReport(),
    step_results=[],
)
```

### Field Access

```python
payload.title          # str
payload.content        # str — full assembled text
payload.sections       # list[PayloadSection]
payload.metadata       # dict[str, Any]
payload.references     # list[Citation]
payload.actions        # list[ActionRecord]
payload.cost_summary   # WorkflowCostReport
payload.step_results   # list[StepResult]

# Serialization
payload.to_dict()      # -> dict[str, Any] (JSON-serializable)
```

## PublisherPlugin Protocol

### Existing Signature (backward-compatible)

```python
class PublisherPlugin(BasePlugin):
    @property
    def plugin_id(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def output_extension(self) -> str: ...

    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path: ...
```

### New Signature (payload-aware)

```python
class PublisherPlugin(BasePlugin):
    # ... existing properties ...

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,
        config: dict[str, Any] | None = None,
    ) -> Path:
        """Publish a full ResultPayload to the target format.

        Args:
            payload: Structured workflow result
            output_path: Destination file path
            layout: Optional layout template for section ordering
            config: Optional publisher-specific configuration (style, etc.)

        Returns:
            Path to the created output file
        """
        ...
```

### Dispatch Rules

The registry calls `publish_payload()` if defined on the publisher. Otherwise,
it falls back to `publish(content=payload.content, output_path=...,
metadata=payload.metadata)`.

## PublisherRegistry

### Publishing

```python
from hiveflow.plugins.publishers import PublisherRegistry

registry = PublisherRegistry()

# Single format
path = await registry.publish_one(
    payload=payload,
    format="markdown",
    output_dir="./output",
    filename="report",
    layout="default",
)

# Multiple formats (primary API)
paths = await registry.publish_all(
    payload=payload,
    formats=["markdown", "pdf", "docx"],
    output_dir="./output",
    filename="report",
    layout="default",
    config={"style": "apa"},
)
# Returns: [Path("./output/report.md"), Path("./output/report.pdf"), ...]
# Missing publishers logged as warnings; other formats still created
```

### Discovery

```python
# List available publishers
available = registry.list()
# -> ["markdown", "json", "html", "pdf", "docx"]

# Check if a publisher is available
registry.has("pdf")  # -> True/False

# Get a specific publisher
publisher = registry.get("markdown")
```

## LayoutTemplate

### Loading

```python
from hiveflow.core.layout import LayoutTemplate, load_layout

# Load by name (searches layouts directory)
layout = load_layout("default")
layout = load_layout("executive-brief")

# List available layouts
from hiveflow.core.layout import list_layouts
names = list_layouts()  # -> ["default", "executive-brief", ...]
```

### Applying

```python
# Layout is applied internally by publishers. Direct usage:
ordered_sections = layout.apply(payload)
# -> list[RenderedSection] in the order defined by the layout template
# Omits optional sections with no content
# Warns on required sections with no content
```

## Completion Callbacks

### Registration

```python
from hiveflow.core.workflow import WorkflowEngine

engine = WorkflowEngine(steps)

# Sync callback
def on_result(payload: ResultPayload) -> None:
    print(f"Workflow complete: {payload.title}")
engine.on_complete(on_result)

# Async callback
async def upload_to_s3(payload: ResultPayload) -> None:
    await s3_client.put(payload.to_dict())
engine.on_complete(upload_to_s3)

# Multiple callbacks (invoked in registration order)
engine.on_complete(on_result)
engine.on_complete(upload_to_s3)
```

### Team Config Integration

```yaml
# team-config.yaml
publish:
  formats: ["markdown", "pdf", "docx"]
  layout: "default"
  style: "apa"
  output_dir: "./output"
  filename: "report"
```

```python
# Engine reads publish config and auto-publishes after execution
result = await engine.execute(agents=agents, initial_state=state)
# If publish config present, files are written automatically
```

## CLI Integration

```bash
# Publish after workflow execution
hiveflow run --template summarizer --query "..." --publish markdown,pdf

# Specify output directory
hiveflow run --template summarizer --query "..." --publish markdown --output-dir ./reports
```

## API Integration

```
GET /api/workflows/{id}
→ Returns ResultPayload as JSON (200 OK)

GET /api/workflows/{id}/export/{format}
→ Returns rendered file (200 OK, Content-Type based on format)
→ 404 if workflow not found
→ 400 if format not available
```
