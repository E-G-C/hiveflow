# Quickstart: Dynamic Agent Collaboration

**Feature**: 010-dynamic-agent-collaboration

## Minimal Configuration

Enable dynamic collaboration on any existing team by adding the `collaboration` section:

```yaml
team_name: adaptive_research
description: Research team with dynamic collaboration
collaboration:
  enabled: true
agents:
  - id: coordinator
    role: Research Coordinator
    system_prompt: |
      You are a research coordinator. When given a complex task:
      1. Break it into independent sub-tasks
      2. Use spawn_agent to recruit specialists from available archetypes
      3. Use delegate_task to assign work to them
      4. Review each result and synthesize a final output
      Available archetypes: researcher, writer, reviewer
    behavior_type: orchestrator
  - id: analyst
    role: Data Analyst
    system_prompt: You are a data analyst specializing in quantitative analysis.
    behavior_type: llm_only
workflow:
  steps:
    - agent: coordinator
      type: sequential
```

## What Happens

When `collaboration.enabled` is `true`, the framework automatically:
1. Injects `delegate_task`, `spawn_agent`, `send_message`, and `read_messages` tools into all orchestrator agents
2. Creates a `CollaborationRuntime` that manages the agent pool, depth tracking, and budget enforcement
3. Makes the archetype library available for dynamic spawning

The orchestrator agent sees these tools alongside any other tools it has, and can use them via normal tool calling.

## Common Patterns

### Pattern 1: Delegate to an existing team member

```
Orchestrator calls delegate_task:
  task: "Analyze the quarterly revenue data"
  delegate_to: "analyst"
  context: {"data": "<revenue figures>"}
```

### Pattern 2: Spawn a specialist and delegate

```
Orchestrator calls spawn_agent:
  archetype: "researcher"
→ Returns: agent_id = "spawned_researcher_0"

Orchestrator calls delegate_task:
  task: "Research competitor pricing models"
  delegate_to: "spawned_researcher_0"
```

### Pattern 3: Spawn a custom agent

```
Orchestrator calls spawn_agent:
  custom_definition:
    role: "Legal Analyst"
    system_prompt: "You are an expert in contract law..."
→ Returns: agent_id = "spawned_legal_analyst_1"
```

### Pattern 4: Inter-agent messaging

```
Agent A calls send_message:
  to: "agent_b"
  subject: "Please review this draft"
  body: "Here is the draft report..."
  requires_response: true

Agent B (on next execution) sees the message in its context
Agent B calls send_message:
  to: "agent_a"
  body: "Feedback: Section 3 needs more detail on..."
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `collaboration.enabled` | `false` | Enable collaboration tools for orchestrators |
| `collaboration.max_delegation_depth` | `3` | Max nesting depth for delegation chains |
| `collaboration.max_spawned_agents` | `10` | Max agents spawnable per execution |
| `collaboration.delegation_timeout_seconds` | `300` | Timeout for each delegation |
| `collaboration.allow_recursive_orchestrators` | `false` | Allow spawned agents to be orchestrators |
| `collaboration.budget_policy` | `"inherit_parent"` | How budgets propagate to children |

## Global Defaults

Set defaults in your hiveflow configuration:

```yaml
# hiveflow config
collaboration_enabled: false
collaboration_max_depth: 3
collaboration_max_spawned: 10
collaboration_timeout: 300
```

Team-level `collaboration` settings override these global defaults.

## Observability

All collaboration events appear in the workflow's event stream:

- `AGENT_SPAWNED` — a new agent was created at runtime
- `DELEGATION_STARTED` / `DELEGATION_COMPLETED` / `DELEGATION_FAILED` — delegation lifecycle
- `MESSAGE_SENT` — an inter-agent message was sent
- `PLAN_CREATED` — a task plan was generated

These events integrate with the existing `StreamChannel` and structured logging.
