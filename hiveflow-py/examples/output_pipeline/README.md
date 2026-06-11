# Output Pipeline Examples

End-to-end examples demonstrating HiveFlow's output pipeline — publishing
workflow results to Markdown, JSON, and other formats.

## Examples

| # | Script | Description | LLM | pypandoc |
|---|--------|-------------|:---:|:-------:|
| 01 | [01_basic_publish.py](01_basic_publish.py) | Simplest path: workflow → Markdown + JSON | Yes | No |
| 02 | [02_sdk_publish.py](02_sdk_publish.py) | Build a rich ResultPayload programmatically | No | No |
| 03 | [03_custom_layout.py](03_custom_layout.py) | Custom layout template for document structure | No | No |
| 04 | [04_completion_callbacks.py](04_completion_callbacks.py) | Sync/async callbacks on workflow completion | Yes | No |
| 05 | [05_auto_publish_config.py](05_auto_publish_config.py) | Auto-publish via `publish` block in team config | Yes | No |
| 06 | [06_publish_pdf_docx.py](06_publish_pdf_docx.py) | Publish to PDF, DOCX, HTML, and all formats | Yes | Yes |
| 07 | [07_fan_out_publish.py](07_fan_out_publish.py) | Parallel fan-out workflow + multi-format publish | Yes | Yes |
| 08 | [08_generated_team_publish.py](08_generated_team_publish.py) | Auto team generation + fan-out + publish | Yes | Yes |

## Quick Start

```bash
# Install hiveflow (Markdown + JSON need no extra deps)
uv pip install -e .

# Run the zero-dependency examples first:
uv run python examples/output_pipeline/02_sdk_publish.py
uv run python examples/output_pipeline/03_custom_layout.py

# For examples that need an LLM, set the Azure endpoint and log in:
export AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
az login   # RBAC auth — no API key needed
uv run python examples/output_pipeline/01_basic_publish.py

# For PDF/DOCX/HTML examples, install the publishers extra:
uv sync --extra publishers --extra llm-azure
uv run python examples/output_pipeline/06_publish_pdf_docx.py
uv run python examples/output_pipeline/07_fan_out_publish.py
uv run python examples/output_pipeline/08_generated_team_publish.py
```

## Supporting Files

```
output_pipeline/
  01_basic_publish.py            # Minimal publish to Markdown + JSON
  02_sdk_publish.py              # Programmatic payload construction
  03_custom_layout.py            # Custom layout template usage
  04_completion_callbacks.py     # Post-workflow callback hooks
  05_auto_publish_config.py      # Auto-publish from engine config
  06_publish_pdf_docx.py         # PDF, DOCX, HTML publishing
  07_fan_out_publish.py          # Fan-out + multi-format publish
  08_generated_team_publish.py   # Auto team gen + fan-out + publish
  team_config.yaml               # Team config YAML with publish block
  layouts/
    executive-brief.yaml         # Custom layout template
```

## Key Concepts

### ResultPayload

The `ResultPayload` is the structured data model that publishers consume. It
contains:

- **title** and **content** (main text)
- **sections** — ordered named content blocks (`PayloadSection`)
- **metadata** — arbitrary key-value pairs (date, workflow_id, etc.)
- **references** — cited sources (`Citation`)
- **actions** — real-world actions taken during execution
- **cost_summary** — per-agent and total token/cost figures

### PublisherRegistry

The `PublisherRegistry` discovers and manages publisher plugins. Built-in
publishers:

- `MarkdownPublisher` — zero-dep, structured `.md` with frontmatter
- `JSONPublisher` — zero-dep, full payload as `.json`
- `HTMLPublisher` — requires `pypandoc`
- `PDFPublisher` — requires `pypandoc` + LaTeX engine
- `DOCXPublisher` — requires `pypandoc`

### Layout Templates

YAML files that define which sections appear in output and in what order. See
`layouts/executive-brief.yaml` for an example. Load with:

```python
from hiveflow import load_layout
layout = load_layout("executive-brief", extra_dirs=["./layouts"])
```

### Completion Callbacks

Register functions that fire after successful workflow execution:

```python
engine.on_complete(my_sync_callback)      # sync
engine.on_complete(my_async_callback)     # async
```

Callbacks receive the `ResultPayload`, execute in registration order, and have
per-callback error isolation (one failure doesn't block the rest).
