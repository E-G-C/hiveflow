# HiveFlow

A reusable, generic multi-agent framework for collaborative LLM workflows.

## Overview

HiveFlow is a flexible multi-agent framework derived from patterns observed in specialized research tools. Rather than building agents hardcoded to a single domain, HiveFlow allows any multi-step collaborative workflow to be assembled from universal agent definitions specialized at creation time.

## TypeScript Rewrite

An experimental TypeScript rewrite now lives under `hiveflow-js/`.

Current scope:

- npm workspace scaffold for the rewrite
- `@hiveflow/core` with an initial agent, workflow, and state runtime slice including sequential execution, parallel fan-out, conditional branching loops, opt-in orchestrator collaboration with runtime spawning and delegation, inline `sub_workflow` composition with nested pause propagation, `action_executor` side-effect agents with approval-aware, error-aware, and rollback-aware recovery semantics, `human_gate` pauses, paused `gated` steps, durable checkpoint-backed resume for paused workflows, serializable workflow definitions plus runtime-catalog cold resume, persisted `TeamConfiguration` and `TeamLibrary` support, reusable `ArchetypeLibrary` definitions plus deterministic `TeamGenerator` composition, a minimal `WorkflowSession` handle, and async session event streaming
- `@hiveflow/provider-ai-sdk` with a Vercel AI SDK Core-backed model adapter, including manual tool-planning support for approval-gated action execution
- subworkflow demo covering named nested workflows with input/output mapping
- subworkflow-pause demo covering nested human-gate pause propagation through a parent workflow checkpoint/resume cycle
- team-config demo covering persisted team configs loaded through `TeamLibrary` and executed through the runtime catalog
- team-generator demo covering archetype discovery and deterministic team composition through reusable archetypes
- llm-team-generator demo covering LLM-guided team generation with JSON validation, capability-gap reporting, and manual review before execution
- dynamic-collaboration demo covering orchestrator-driven agent spawning, targeted delegation, and collaboration event emission
- action-executor demo covering approval, resume, and audited side effects
- action-error demo covering `confirm_on_error` escalation and acknowledgement-driven resume
- action-rollback demo covering `rollback_on_failure` recovery for automatic side effects
- live branching demo covering fan-out plus revision routing
- checkpoint demo covering definition-backed save, reload, and cold resume for paused sessions
- session-events demo covering `WorkflowSession.events()` across pause/resume
- live `demo:smoke` runner covering every TypeScript demo against a configured OpenAI-compatible endpoint
- shared live OpenAI-compatible example helper plus a dedicated connectivity demo using `claude-opus-4-6` by default for reachable endpoints, with chat mode as the safe default for OpenAI-compatible proxies

This rewrite is greenfield and intentionally not API-compatible with the Python package. The current implementation notes and commands are documented in `hiveflow-js/README.md`.

## Key Features

- **Universal Agent Class**: Single parameterized agent specialized through configuration (system prompt, tools, behavior type, model)
- **Dynamic Team Composition**: Template-based or LLM-generated team configurations
- **Workflow Graph Engine**: Sequential, parallel fan-out, conditional branching, and human-in-the-loop execution
- **Checkpoint & Resume**: Automatic checkpointing at gates, resume from any saved checkpoint, checkpoint history via `list_checkpoints()`
- **Plugin Architecture**: Extensible tools, LLM providers, embeddings, retrievers, scrapers, publishers, and document loaders
- **MCP Integration**: Connect to external tool servers via Model Context Protocol (stdio/HTTP), with three-tier strategy (disabled/fast/deep) and MCP gateway for exposing workflows to external clients
- **Deep Research**: Recursive multi-level research with breadth-first query trees
- **Resilient Execution**: Fallback chains, circuit breakers, bulkhead semaphores, rate limiting
- **Cost Tracking**: Per-agent and per-workflow token usage and cost estimation
- **Real-time Streaming**: Async pub/sub event streaming with WebSocket support
- **Source Citations**: Automatic citation tracking with APA/numbered/inline formatting
- **Context Compression**: Deduplication, relevance scoring, and word budget fitting
- **Multi-format Output**: Markdown, JSON, HTML, PDF, DOCX export via publisher plugins with layout templates and auto-publish

## Output Pipeline

HiveFlow assembles workflow results into a structured `ResultPayload` and publishes to multiple formats:

```python
# Auto-publish via team config
engine = WorkflowEngine(steps, publish_config={
    "formats": ["markdown", "json"],
    "output_dir": "./output",
})

# Or publish manually
from hiveflow.plugins.publishers import PublisherRegistry, MarkdownPublisher
from hiveflow.plugins.publishers.json_publisher import JSONPublisher

registry = PublisherRegistry(drop_in_dir=None)
registry.register(MarkdownPublisher())
registry.register(JSONPublisher())

paths = await registry.publish_all(
    result.result_payload, "./output", ["markdown", "json"], filename="report",
)
```

**Built-in formats**: Markdown (zero-dep), JSON (zero-dep), HTML, PDF, DOCX (via pypandoc)

Install pypandoc publishers: `uv sync --extra publishers`

## Architecture

```
hiveflow/
├── core/                     # Core framework
│   ├── agent.py              # Universal Agent class (4 behavior types)
│   ├── workflow.py            # Workflow Graph Engine
│   ├── schema.py              # Team Configuration Schema (Pydantic)
│   ├── state.py               # Workflow state container
│   ├── config.py              # Layered configuration system
│   ├── registry.py            # Plugin discovery (entry points + drop-in)
│   ├── fallback.py            # LLM fallback chains
│   ├── observability.py       # Structured logging + OpenTelemetry
│   └── ...                    # research, citations, compression, streaming, cost, errors
├── plugins/
│   ├── tools/                 # Tool plugins (search, scrape, etc.)
│   ├── llm/                   # LLM providers (OpenAI, Anthropic, Azure, Perplexity)
│   ├── mcp/                   # MCP integration (bridge, manager, gateway)
│   ├── embeddings/            # Embedding providers + vector store
│   ├── documents/             # Document loaders
│   └── ...                    # retrievers, scrapers, publishers
├── api/                       # FastAPI backend
└── templates/                 # Bundled team configurations
```

See [docs/architecture.md](docs/architecture.md) for the full directory listing and component narratives.

## Quick Start

This project uses [uv](https://github.com/astral-sh/uv) for package management.
The Python implementation lives in the `hiveflow-py/` directory of the repository.

```bash
git clone <repo-url>
cd hiveflow/hiveflow-py
uv venv
uv sync
```

### Minimal Example

```python
import asyncio
from hiveflow import (
    Agent, AgentBehaviorType, WorkflowEngine, WorkflowStep,
)

async def main():
    researcher = Agent(
        agent_id="researcher",
        role="Researcher",
        system_prompt="Find relevant information about the given topic.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model="openai:gpt-4o",
    )
    writer = Agent(
        agent_id="writer",
        role="Writer",
        system_prompt="Write a clear summary based on research findings.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model="openai:gpt-4o",
    )

    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]
    engine = WorkflowEngine(steps)

    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Explain quantum computing"},
    )
    print(f"Status: {result.status}")
    print(f"Output: {result.state}")

asyncio.run(main())
```

## Agent Behavior Types

| Type | Description |
|------|-------------|
| `llm_only` | Pure LLM response -- receives state, generates text output |
| `tool_user` | LLM with tool access -- can call registered tool plugins |
| `orchestrator` | Spawns and manages sub-workflows |
| `human_gate` | Pauses for human approval/input before continuing |

## Three-Tier LLM Selection

| Tier | Default | Use Case |
|------|---------|----------|
| `$FAST_LLM` | `openai:gpt-4o-mini` | Quick operations, formatting |
| `$SMART_LLM` | `openai:gpt-4o` | Primary reasoning, research |
| `$STRATEGIC_LLM` | `openai:o3-mini` | Complex planning, orchestration |

## MCP Integration

HiveFlow integrates with the [Model Context Protocol](https://modelcontextprotocol.io/) to connect agents to external tool servers.

Install the optional dependency: `uv sync --extra mcp`

Configure MCP servers in `.hiveflow/mcp.json`:

```json
{
  "strategy": "fast",
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    },
    {
      "name": "slack",
      "transport": "http",
      "url": "https://mcp.slack.example.com",
      "auth": { "type": "bearer", "env": "SLACK_MCP_TOKEN" }
    }
  ]
}
```

**Strategy modes**:

| Mode | Behavior |
|------|----------|
| `disabled` | No MCP servers contacted |
| `fast` | All discovered tools injected into agents |
| `deep` | LLM selects relevant tool subset per task |

Override per team with `mcp_strategy` in the team configuration.

See [`specs/007-mcp-memory-integrations/quickstart.md`](../specs/007-mcp-memory-integrations/quickstart.md) for detailed examples.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Team configs, programmatic workflows, templates, deep research, Chat UI |
| [LLM Providers](docs/llm-providers.md) | OpenAI, Anthropic, Azure RBAC, Perplexity Sonar, secret backends, fallback chains, observability |
| [Plugins](docs/plugins.md) | Creating tool plugins, custom LLM providers, plugin types and discovery |
| [Configuration](docs/configuration.md) | Environment variables, tier variables, config layering |
| [Architecture](docs/architecture.md) | Directory structure, core components, LLM system, resilience patterns |

See also [`examples/llm_providers/`](examples/llm_providers/) for runnable examples covering provider discovery, chat, streaming, Azure RBAC, secret backends, tier variables, fallback chains, observability, multi-turn conversations, function calling, and JSON mode.

To run agents against Perplexity Sonar, set `PERPLEXITY_API_KEY` and use model references such as `perplexity:sonar-pro` or `perplexity:sonar-reasoning-pro`.

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Install Azure extras (optional)
uv sync --extra llm-azure

# Install HuggingFace embeddings (optional)
uv sync --extra embeddings-huggingface

# Run tests
uv run pytest

# Run linting
uv run ruff check hiveflow/ tests/

# Run type checking (strict mode)
uv run mypy hiveflow/
```

## Project Status

All core framework components are implemented with comprehensive test coverage at 81%:

- Core: Universal Agent, Workflow Engine, Schema, State, Config
- Infrastructure: JSON resilience, Fallback chains, Streaming, Cost tracking
- Error handling: Circuit breaker, Bulkhead, Rate limiting
- Plugins: Tools, LLM providers (OpenAI, Anthropic, Azure, Perplexity), Embeddings, Retrievers, Scrapers, Publishers, Document loaders
- LLM: Provider auto-discovery, SecretBackend, structured logging, OpenTelemetry, Azure RBAC
- Data: Citations, Compression, Prompt templates, Team templates
- Features: Deep research, Team generation, Document input pipeline
- API: FastAPI backend

## Requirements

See the [requirements specifications](../requirements/README.md) for the comprehensive requirements documents.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

Inspired by patterns from the [gpt-researcher](https://github.com/assafelovic/gpt-researcher) project.
