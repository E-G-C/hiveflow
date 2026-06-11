# Getting Started with HiveFlow

Introductory examples that demonstrate HiveFlow's core concepts. Start here
if you're new to the framework.

## Examples

| # | Script | What it shows | API Key? |
|---|--------|---------------|:--------:|
| 01 | `01_basic_workflow.py` | Two-agent sequential workflow with mock LLM | No |
| 02 | `02_team_config.py` | Load and validate a team configuration file | No |
| 03 | `03_generated_team.py` | Dynamic team generation from a task description | No |

## Running

```bash
# All examples run without API keys (mock providers)
uv run python examples/getting_started/01_basic_workflow.py
uv run python examples/getting_started/02_team_config.py
uv run python examples/getting_started/03_generated_team.py
```

## Key Concepts

- **Agent** — a unit of work with a role, system prompt, and behavior type
- **WorkflowStep** — defines how agents connect (sequential, parallel, conditional)
- **WorkflowEngine** — executes the step graph and manages state propagation
- **TeamConfiguration** — a validated schema for team definitions (JSON/dict)
- **TeamGenerator** — generates team configurations from task descriptions
