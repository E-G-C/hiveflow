# Quickstart: Configuration & Operations

**Feature**: 008-config-operations

---

## 1. Configuration — Layered Settings

No code changes needed. Just set environment variables or create a config file:

```bash
# Environment variables (highest precedence after team overrides)
export HIVEFLOW_SMART_LLM="anthropic:claude-sonnet-4-20250514"
export HIVEFLOW_MAX_TOKENS=8000
export HIVEFLOW_SOURCE_MODE="hybrid"
export HIVEFLOW_DOC_PATH="/data/docs"
export HIVEFLOW_DEFAULT_ACTION_POLICY="allow"
```

Or use a project config file (`hiveflow.yaml`):

```yaml
SMART_LLM: "anthropic:claude-sonnet-4-20250514"
MAX_TOKENS: 8000
SOURCE_MODE: hybrid
DOC_PATH: /data/docs
DEFAULT_ACTION_POLICY: allow
ACTION_TIMEOUT: 60
MCP_STRATEGY: fast
```

Precedence: defaults → config file → environment → team overrides.

## 2. Resilience — Automatic Fallback

Agents automatically get fallback chains, rate limiting, and circuit breaking:

```python
from hiveflow import HiveFlow

hf = HiveFlow()  # resilience is built in
result = await hf.run(template="researcher", query="Analyze market trends")

# Cost data is included automatically
print(result.cost_summary.total_cost_usd)
print(result.cost_summary.by_agent)
```

If the Strategic LLM fails, the framework automatically tries:
1. Strategic model at 50% max_tokens
2. Smart model at full max_tokens
3. Smart model at 50% max_tokens
4. Fast model
5. Error (only after all options exhausted)

## 3. Prompt Templates — Categorized Library

```python
from hiveflow.core.prompts import PromptLibrary

library = PromptLibrary.default()

# Get a categorized template
template = library.get("report_writing")

# Render with dotted-path variables
prompt = template.render({
    "task": {"description": "Market analysis", "subtopic": "AI trends"},
    "config": {"language": "english", "tone": "analytical"},
})
```

## 4. Streaming — Real-Time Observability

```python
from hiveflow.core.streaming import StreamChannel

channel = StreamChannel()

# Subscribe to events
async def on_event(event):
    print(f"[{event.type}] {event.agent_id}: {event.content}")
    if event.metadata:
        print(f"  tokens={event.metadata.tokens_used}, cost=${event.metadata.cost_usd}")

channel.subscribe(on_event)

# JSON-lines audit log is automatic when OUTPUT_DIR is configured
```

## 5. Recursive Exploration

```yaml
# In team config
agents:
  - id: explorer
    role: "Deep research explorer"
    behavior_type: orchestrator
    config:
      breadth: 3
      depth: 2
      concurrency: 4
```

```python
result = await hf.run(template="deep_research", query="Comprehensive AI safety analysis")
# Progress is reported via stream events
# Results are automatically merged from all branches
```
