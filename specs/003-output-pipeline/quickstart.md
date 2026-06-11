# Quickstart: Output Pipeline

**Feature**: 003-output-pipeline

## Prerequisites

```bash
# Install with publisher support
uv add hiveflow[publishers]

# This installs pypandoc + pypandoc_binary (bundles pandoc)
# For PDF output, you also need a LaTeX engine:
# - macOS: brew install --cask mactex-no-gui
# - Ubuntu: apt install texlive-xetex
# - Windows: choco install miktex
# - Or use TinyTeX: https://yihui.org/tinytex/
```

## 1. Publish Workflow Results (Simplest Path)

Add a `publish` block to your team config:

```yaml
# team-config.yaml
name: "Research Team"
agents:
  - id: researcher
    role: Researcher
    system_prompt: "Research the given topic."
    behavior_type: llm_only
    model: openai:gpt-4o

  - id: writer
    role: Writer
    system_prompt: "Write a clear report from the research."
    behavior_type: llm_only
    model: openai:gpt-4o

workflow:
  - agent: researcher
    step_type: sequential
    next_step: writer
  - agent: writer
    step_type: sequential

# NEW: output pipeline config
publish:
  formats: ["markdown", "pdf"]
  output_dir: "./output"
```

Run the workflow:

```bash
hiveflow run --config team-config.yaml --query "Explain quantum computing"
# → ./output/output.md
# → ./output/output.pdf
```

## 2. Publish Programmatically (SDK)

```python
import asyncio
from hiveflow import Agent, AgentBehaviorType, WorkflowEngine, WorkflowStep
from hiveflow.plugins.publishers import PublisherRegistry

async def main():
    # Set up agents and workflow (same as before)
    researcher = Agent(
        agent_id="researcher",
        role="Researcher",
        system_prompt="Research the topic.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model="openai:gpt-4o",
    )
    writer = Agent(
        agent_id="writer",
        role="Writer",
        system_prompt="Write a report.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model="openai:gpt-4o",
    )

    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]
    engine = WorkflowEngine(steps)

    # Execute workflow
    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Explain quantum computing"},
    )

    # Assemble result payload
    from hiveflow.core.result_payload import ResultPayload
    payload = ResultPayload.from_workflow_result(result)

    # Publish to multiple formats
    registry = PublisherRegistry()
    paths = await registry.publish_all(
        payload=payload,
        formats=["markdown", "json", "pdf"],
        output_dir="./output",
        filename="quantum-report",
    )
    print(f"Published: {[str(p) for p in paths]}")

asyncio.run(main())
```

## 3. Use a Custom Layout Template

Create a layout file:

```yaml
# layouts/executive-brief.yaml
name: executive-brief
description: Concise executive briefing format
sections:
  - id: title
    source: metadata.title
    required: true
  - id: executive_summary
    source: sections.executive_summary
    required: true
  - id: findings
    source: content
    required: true
  - id: references
    source: references
    required: false
```

Reference it in your team config:

```yaml
publish:
  formats: ["markdown", "pdf"]
  layout: "executive-brief"
  output_dir: "./output"
```

## 4. Register a Completion Callback

```python
from hiveflow.core.result_payload import ResultPayload

async def send_to_slack(payload: ResultPayload) -> None:
    """Post a summary to Slack when the workflow completes."""
    # Your Slack integration here
    print(f"Workflow '{payload.title}' completed with {len(payload.sections)} sections")

engine = WorkflowEngine(steps)
engine.on_complete(send_to_slack)

result = await engine.execute(agents=agents, initial_state=state)
# send_to_slack is called automatically after execution
```

## 5. Access Results via API

```bash
# Get structured result
curl http://localhost:8000/api/workflows/{id}
# → JSON ResultPayload

# Export as PDF
curl -o report.pdf http://localhost:8000/api/workflows/{id}/export/pdf
```

## Available Formats

| Format | Publisher ID | Dependencies | Output |
|--------|-------------|--------------|--------|
| Markdown | `markdown` | None | `.md` file |
| JSON | `json` | None | `.json` file |
| HTML | `html` | pypandoc, jinja2 | `.html` file |
| PDF | `pdf` | pypandoc, LaTeX engine | `.pdf` file |
| DOCX | `docx` | pypandoc | `.docx` file |

Markdown and JSON publishers work without any optional dependencies.
HTML, PDF, and DOCX require `hiveflow[publishers]`.
PDF additionally requires a LaTeX engine installed on the system.
