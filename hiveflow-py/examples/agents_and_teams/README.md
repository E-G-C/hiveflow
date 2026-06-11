# Agents & Teams Examples

Live examples demonstrating the HiveFlow agents-and-teams feature set.
Default to Azure OpenAI with Entra ID RBAC authentication.

## Prerequisites

```bash
# Install with Azure extras
uv sync --extra llm-azure

# Authenticate (pick one)
az login                              # Interactive browser login
# or set AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_CLIENT_SECRET for service principal
```

Set `AZURE_OPENAI_ENDPOINT` or use the pre-configured default in each script.

## Examples

| # | Script | Feature | API Key? |
|---|--------|---------|:--------:|
| 01 | `01_team_from_config.py` | Define and run a team from inline config | Azure |
| 02 | `02_failure_policies.py` | Per-agent `on_failure` policies: fail, retry, skip | Azure |
| 03 | `03_archetypes.py` | Browse and compose teams from archetype library | Azure |
| 04 | `04_action_policies.py` | Action executor with dry_run, require_approval | Azure |
| 05 | `05_conditional_workflow.py` | Conditional steps with review loop | Azure |
| 06 | `06_parallel_fanout.py` | Parallel fan-out with namespaced results | Azure |
| 07 | `07_llm_team_generation.py` | LLM-generated team composition + gap detection | Azure |
| 08 | `08_e2e_llm_team.py` | Full pipeline: LLM generates team → build → execute → publish | Azure |
| 09 | `09_context_management.py` | All 10 context management strategies with instrumentation | Azure |
| 10 | `10_task_driven_pipeline.py` | Task-driven multi-agent pipeline with phased execution | Azure |
| 11 | `11_delegation.py` | Dynamic delegation — orchestrator delegates to team members | Azure |
| 12 | `12_spawn_and_delegate.py` | Spawn specialists from archetypes and delegate work | Azure |
| 13 | `13_collaborative_planning.py` | Structured task planning with concurrent execution | Azure |
| 14 | `14_full_auto_pipeline.py` | Full-auto: file in → LLM designs team → collaboration → multi-format out | Azure |
| 15 | `15_task_preprocessing.py` | Task preprocessing: automatic chunking and summarization for large inputs | Azure |
| 16 | `16_large_input_processing.py` | Large-input pipeline: preprocessing → LLM team generation → execution → output | Azure |

### Task Files

The `tasks/` subdirectory contains sample task files used as input:

| File | Description |
|------|-------------|
| `tasks/sample_task.md` | Enterprise cloud migration strategy assessment |
| `tasks/ai_code_review_brief.md` | AI-powered code review platform product brief |
| `tasks/td.md` | Transcript-to-documentation prompt (instructions for processing transcripts) |
| `tasks/aw.txt` | Sample WebVTT meeting transcript (~16K words, used with `td.md`) |

## Running

```bash
# Run any example:
uv run python examples/agents_and_teams/01_team_from_config.py

# Override deployment name:
AZURE_OPENAI_DEPLOYMENT=gpt-4o uv run python examples/agents_and_teams/01_team_from_config.py
```

## Notes

- **Archetype tools**: The built-in `researcher` archetype declares `tools: ["web_search"]`.
  When composing teams from archetypes without a registered `web_search` plugin,
  examples strip the `tools` list and fall back to `llm_only` behavior (see example 03).
- **Example 05 (conditional workflow)**: The review loop may exhaust `max_iterations`
  if the LLM reviewer keeps rejecting. This is expected LLM-dependent behavior, not a bug.
- **YAML front matter**: When publishing Markdown with pandoc, titles containing
  colons must be quoted in the YAML front matter to avoid parse errors.
