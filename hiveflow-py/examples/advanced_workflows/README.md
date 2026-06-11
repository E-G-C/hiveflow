# Advanced Workflow Examples

Complex multi-agent patterns demonstrating HiveFlow's divide-and-conquer,
dynamic team generation, and recursive research capabilities.

## Examples

| # | Script | What it shows | LLM? |
|---|--------|---------------|:----:|
| 01 | `01_fan_out_report.py` | Planner → parallel writers → assembly | Yes |
| 02 | `02_fan_out_generated.py` | Fan-out with dynamic team generation | Yes |
| 03 | `03_deep_research.py` | Recursive branching research (mock) | No |
| 04 | `04_team_builder.py` | Generate team blueprint + publish | No |

## Running

```bash
# Mock example (no API key):
uv run python examples/advanced_workflows/03_deep_research.py
uv run python examples/advanced_workflows/04_team_builder.py

# With Azure OpenAI:
AZURE_OPENAI_ENDPOINT=https://<resource>.cognitiveservices.azure.com \
    uv run python examples/advanced_workflows/01_fan_out_report.py
```

## Key Concepts

- **Orchestrator decomposition** — a planner agent breaks tasks into sub-tasks
- **Parallel fan-out** — sub-tasks execute in parallel, results collected
- **Code-level assembly** — final output stitched by Python, not an LLM
- **TeamGenerator** — create team configs from task descriptions
- **Recursive research** — deep branching exploration of complex topics
- **ResultPayload + Publishers** — format and publish workflow outputs
