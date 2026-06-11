# Core Architecture Examples

Examples demonstrating HiveFlow's core architecture features. Most use mock
providers and **run without API keys**.

## Examples

| # | File | Feature | API Key? |
|---|------|---------|:--------:|
| 01 | `01_hiveflow_facade.py` | HiveFlow entry point: `run_sync()`, inline team config, session inspection | No |
| 02 | `02_action_executor.py` | Action executor with `auto` and `require_approval` safety policies | No |
| 03 | `03_gated_workflow.py` | Gated workflow steps that pause for external approval | No |
| 04 | `04_checkpointing.py` | Durable checkpointing with `FileCheckpointStorage`, accumulation, list, rewind | No |
| 05 | `05_session_lifecycle.py` | `WorkflowSession` status tracking, pause/resume/cancel, JSON serialization | No |
| 06 | `06_model_requirements.py` | Declarative model selection via `ModelRequirements` and tier variables | No |
| 07 | `07_discovery_apis.py` | Enumerate teams, archetypes, tools, and models | No |
| 08 | `08_state_schema.py` | State schema enforcement modes: `warn`, `strict`, `off` | No |
| 09 | `09_checkpoint_resume.py` | End-to-end checkpoint/resume: execute → pause → checkpoint → resume | No* |
| 10 | `10_workflow_events.py` | Event stream: step_start, step_complete, gate_requested, checkpoint_saved | No* |

\* Set `AZURE_OPENAI_ENDPOINT` to use Azure OpenAI instead of mock responses.

## Prerequisites

```bash
# Install HiveFlow
uv sync

# For LLM-powered examples, set up a provider:
export OPENAI_API_KEY=sk-...
# or use a local OpenAI-compatible server
```

Most examples use mock providers and run without any API keys. Examples that
need a real LLM are noted in their docstrings.

## Running

```bash
uv run python examples/core_architecture/01_hiveflow_facade.py
uv run python examples/core_architecture/02_action_executor.py
# etc.
```
