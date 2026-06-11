[< Back to Index](README.md)

---

# 13 — Dynamic Agent Collaboration

> **Version:** 1.0
> **Date:** 2026-03-04
> **Status:** Draft
> **Dependencies:** [01-core-architecture](01-core-architecture.md),
> [02-workflows](02-workflows.md), [03-agents-and-teams](03-agents-and-teams.md),
> [04-plugins](04-plugins.md)

---

## Objective

Enable agents within a running workflow to **dynamically collaborate** at
runtime — decomposing tasks, delegating work, recruiting specialist agents,
and communicating directly — without requiring the full workflow graph to be
defined ahead of time.

Today, hiveflow supports three team composition modes (template, custom,
LLM-generated), but all operate **before execution begins**. Once a workflow
starts, the agent roster and execution graph are fixed. This requirement adds
a fourth dimension: **runtime collaboration**, where orchestrator-class agents
can form sub-teams, delegate tasks, and coordinate agents on the fly during
execution.

This is **additive** to the existing architecture. All current team composition
modes, workflow step types, and agent behavior types remain unchanged.

---

## Motivation

Real-world complex tasks are rarely fully decomposable upfront. An agent
researching a topic might discover a sub-problem that requires a specialist
(e.g., a legal analyst, a data scientist). A planner might break a task into
sub-tasks whose count and nature are only known after initial analysis. An
agent might need to ask another agent a clarifying question rather than
blindly passing state through a pipeline.

The current architecture handles the static case well. This requirement
addresses the dynamic case, where the **team evolves as the problem unfolds**.

---

## Core Capabilities

### Capability 1 — Runtime Task Delegation

An orchestrator agent can delegate a sub-task to another agent (or a
dynamically assembled sub-team) during its own execution, wait for the result,
and incorporate it into its output.

**What this enables:**
- An agent encountering a sub-problem it can't handle delegates to a specialist
- Recursive decomposition: a planner creates sub-tasks and delegates each one
- On-demand expert consultation without pre-wiring the workflow graph

### Capability 2 — Dynamic Agent Spawning

An orchestrator agent can instantiate new agents at runtime from the
archetype library (or from inline definitions), register them in the
running workflow's agent pool, and dispatch work to them.

**What this enables:**
- Team size adapts to the problem ("I need 3 researchers, not 1")
- Specialist agents spun up on demand ("I need a legal analyst for this")
- The LLM decides which archetypes to recruit based on discovered requirements

### Capability 3 — Inter-Agent Messaging

Agents can send targeted messages to other agents and read messages addressed
to them, enabling request-response patterns, negotiation, and information
sharing beyond the linear state pipeline.

**What this enables:**
- A reviewer can ask the writer a clarifying question
- A researcher can broadcast a finding to all interested agents
- Agents can negotiate priorities or resolve conflicts

### Capability 4 — Collaborative Task Planning

An orchestrator agent can analyze a complex task, decompose it into sub-tasks
with dependency relationships, assign each sub-task to the most appropriate
agent (existing or newly spawned), and coordinate their parallel or sequential
execution.

**What this enables:**
- Given "Build a marketing campaign", the orchestrator dynamically creates
  a copywriter, a designer brief, a social strategist, and a metrics analyst,
  wires them into a mini-workflow, and runs it
- The decomposition is informed by what archetypes are available and what tools
  are registered

---

## Architecture

### Design Principles

| Principle | Implication |
|---|---|
| **Additive, not invasive** | New capabilities are exposed as tool plugins and state conventions — no changes to `Agent`, `WorkflowEngine`, or `TeamConfiguration` core classes |
| **Orchestrator-gated** | Only agents with `orchestrator` behavior type can spawn agents, delegate tasks, or compose sub-teams. This prevents runaway agent proliferation |
| **State-compatible** | All inter-agent communication flows through the existing shared state dict, using well-defined key conventions. No new transport layer |
| **Auditable** | All delegation, spawning, and messaging events are logged to the workflow's event stream and audit trail |
| **Budget-bounded** | Spawned agents and delegated tasks inherit the parent's cost/token budgets with configurable sub-budgets to prevent unbounded resource consumption |
| **Recursion-limited** | Maximum delegation depth is configurable (default: 3) to prevent infinite loops of agents spawning agents |

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                  Orchestrator Agent                      │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ DelegateTool │  │ SpawnAgent   │  │ MessageTool  │  │
│  │              │  │ Tool         │  │              │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │          │
└─────────┼─────────────────┼──────────────────┼──────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│                  Collaboration Runtime                   │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Delegation   │  │ Agent Pool   │  │ Message Bus  │  │
│  │ Executor     │  │ (Registry)   │  │              │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ Archetype    │  │ Budget       │                     │
│  │ Library      │  │ Controller   │                     │
│  └──────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

---

## Detailed Design

### 1. Delegation Tool (`DelegateTaskTool`)

A tool plugin available to `orchestrator` agents that delegates a sub-task
to another agent (by ID) or to a dynamically composed sub-team.

#### Tool Spec (LLM-facing)

```json
{
  "name": "delegate_task",
  "description": "Delegate a sub-task to another agent or a sub-team. The task will be executed and the result returned to you.",
  "parameters": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "Clear description of the sub-task to delegate"
      },
      "delegate_to": {
        "type": "string",
        "description": "Agent ID to delegate to, or 'auto' to let the system choose the best agent"
      },
      "context": {
        "type": "object",
        "description": "Additional context to pass to the delegate (merged into its state)"
      },
      "expected_output": {
        "type": "string",
        "description": "What kind of output you expect back (text, structured_data, decision)"
      }
    },
    "required": ["task"]
  }
}
```

#### Execution Flow

1. The orchestrator agent calls `delegate_task` via normal tool calling
2. `DelegateTaskTool.execute()` resolves the target agent:
   - If `delegate_to` is an existing agent ID → use that agent
   - If `delegate_to` is `"auto"` → match task description against archetype
     metadata (tags, description) to select the best fit
   - If no match found → spawn a default `llm_only` agent with the task as
     its system prompt
3. Construct a sub-state from the parent state + provided context
4. Call `target_agent.execute(sub_state)` and await the result
5. Return the result to the orchestrator as the tool's output
6. Log a `delegation_completed` event to the stream channel

#### Delegation Context Isolation

The delegated agent receives a **filtered copy** of the parent state, not the
full state. By default:
- Includes: `task` (overwritten with the delegated task), any keys in `context`
- Excludes: Internal keys (prefixed with `_`), other agents' raw outputs
- Includes if present: `documents`, `document_summary` (shared knowledge)

This follows the same principle as the state schema `agent_io` enforcement
(see [03-agents-and-teams — State Schema](03-agents-and-teams.md)).

### 2. Agent Spawning Tool (`SpawnAgentTool`)

A tool plugin that creates new agents at runtime from archetypes or inline
definitions.

#### Tool Spec (LLM-facing)

```json
{
  "name": "spawn_agent",
  "description": "Create a new specialist agent from an archetype or custom definition. Returns the agent's ID for use with delegate_task.",
  "parameters": {
    "type": "object",
    "properties": {
      "archetype": {
        "type": "string",
        "description": "Name of an archetype from the library (e.g., 'researcher', 'writer', 'reviewer')"
      },
      "custom_definition": {
        "type": "object",
        "description": "Inline agent definition if no archetype fits. Must include 'role' and 'system_prompt'.",
        "properties": {
          "role": { "type": "string" },
          "system_prompt": { "type": "string" },
          "behavior_type": { "type": "string", "default": "llm_only" },
          "tools": { "type": "array", "items": { "type": "string" } }
        }
      },
      "agent_id": {
        "type": "string",
        "description": "Optional custom ID for the spawned agent. Auto-generated if omitted."
      }
    }
  }
}
```

#### Execution Flow

1. Orchestrator calls `spawn_agent` with an archetype name or inline definition
2. `SpawnAgentTool.execute()`:
   - Validates the request (archetype exists, or inline definition is valid)
   - Checks recursion depth and budget limits
   - Creates an `Agent` instance using the same `LLMProvider` and `LLMConfig`
     as the parent orchestrator (inherited context)
   - Resolves tool references against the `ToolRegistry`
   - Generates a unique `agent_id` if not provided (format: `spawned_{archetype}_{counter}`)
   - Registers the agent in the workflow's runtime agent pool
3. Returns the `agent_id` to the orchestrator for use with `delegate_task`
4. Logs a `agent_spawned` event to the stream channel

#### Constraints

- **Spawned agents cannot be orchestrators** (by default) — prevents recursive
  spawning storms. This can be overridden via configuration:
  `allow_recursive_orchestrators: true` with a mandatory `max_delegation_depth`
- **Spawned agents inherit the parent's model tier** unless the archetype
  specifies a different model
- **Tool access is additive** — spawned agents can only use tools that are
  registered in the global `ToolRegistry`. They cannot conjure new tools
- **Spawned agents are ephemeral** — they exist only for the duration of the
  current workflow execution. They are not persisted to the team config

### 3. Inter-Agent Messaging (`MessageTool`)

A tool plugin enabling agents to send and receive targeted messages via the
shared workflow state.

#### Tool Spec (LLM-facing)

```json
{
  "name": "send_message",
  "description": "Send a message to another agent. The message will be available in their next execution context.",
  "parameters": {
    "type": "object",
    "properties": {
      "to": {
        "type": "string",
        "description": "Target agent ID, or 'broadcast' to send to all agents"
      },
      "subject": {
        "type": "string",
        "description": "Brief subject line for the message"
      },
      "body": {
        "type": "string",
        "description": "The message content"
      },
      "requires_response": {
        "type": "boolean",
        "description": "Whether you need a response from the target agent",
        "default": false
      }
    },
    "required": ["to", "body"]
  }
}
```

#### State Convention

Messages are stored in the shared state under a `_messages` key:

```python
state["_messages"] = {
    "agent_id_1": [
        {
            "from": "orchestrator",
            "to": "agent_id_1",
            "subject": "Clarification needed",
            "body": "Can you verify the Q3 numbers?",
            "requires_response": True,
            "timestamp": "2026-03-04T10:30:00Z",
            "read": False,
        }
    ],
    "_broadcast": [
        {
            "from": "researcher",
            "to": "broadcast",
            "subject": "Key finding",
            "body": "Market share data suggests...",
            "timestamp": "2026-03-04T10:31:00Z",
        }
    ]
}
```

#### Message Delivery

Messages are **not delivered in real-time** — they are written to state and
read by the target agent on its next execution. This matches hiveflow's
existing execution model where agents interact through shared state.

When an agent executes, its `_summarize_state()` method includes any unread
messages addressed to it. After processing, messages are marked as `read`.

A `ReadMessagesTool` is also provided for agents that want to explicitly
check their inbox:

```json
{
  "name": "read_messages",
  "description": "Read messages sent to you by other agents.",
  "parameters": {
    "type": "object",
    "properties": {
      "unread_only": { "type": "boolean", "default": true }
    }
  }
}
```

### 4. Collaborative Task Planner

A higher-level pattern that composes the delegation and spawning tools into a
**plan-and-execute** loop. This is not a separate component but rather a
**system prompt pattern + tool composition** for orchestrator agents.

#### Planning Prompt Pattern

When an orchestrator agent is given the delegation and spawning tools, its
system prompt should instruct it to:

1. **Analyze** the task and identify sub-tasks
2. **Assess** what expertise is needed for each sub-task
3. **Recruit** agents (spawn from archetypes or use existing team members)
4. **Delegate** each sub-task to the assigned agent
5. **Collect** results and synthesize them into a coherent output
6. **Iterate** if any sub-task results are insufficient

#### Example System Prompt Fragment

```
You are a task coordinator. When given a complex task:

1. Break it into independent sub-tasks
2. For each sub-task, decide which specialist to assign:
   - Use `spawn_agent` to recruit specialists from available archetypes
   - Use `delegate_task` to assign work to them
3. Review each result. If quality is insufficient, re-delegate with feedback.
4. Synthesize all results into your final output.

Available archetypes: {archetype_list}
Active agents: {agent_list}
```

#### Plan Schema

The planner produces a structured plan before execution:

```json
{
  "plan": {
    "sub_tasks": [
      {
        "id": "st_1",
        "description": "Research competitor pricing models",
        "assigned_to": "auto",
        "archetype_hint": "researcher",
        "depends_on": [],
        "expected_output": "structured_data"
      },
      {
        "id": "st_2",
        "description": "Analyze our cost structure",
        "assigned_to": "auto",
        "archetype_hint": "researcher",
        "depends_on": [],
        "expected_output": "structured_data"
      },
      {
        "id": "st_3",
        "description": "Write pricing recommendation",
        "assigned_to": "auto",
        "archetype_hint": "writer",
        "depends_on": ["st_1", "st_2"],
        "expected_output": "text"
      }
    ]
  }
}
```

Independent sub-tasks (no dependencies) can be executed in parallel via
`asyncio.gather()`. Dependent sub-tasks wait for their prerequisites.

---

## Configuration

### Team-Level Configuration

Dynamic collaboration is configured at the team level in the `TeamConfiguration`:

```json
{
  "team_name": "adaptive_research",
  "collaboration": {
    "enabled": true,
    "max_delegation_depth": 3,
    "max_spawned_agents": 10,
    "allow_recursive_orchestrators": false,
    "delegation_timeout_seconds": 300,
    "budget_policy": "inherit_parent"
  },
  "agents": [ ... ],
  "workflow": { ... }
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Whether dynamic collaboration tools are injected into orchestrator agents |
| `max_delegation_depth` | `int` | `3` | Maximum nesting depth for delegations |
| `max_spawned_agents` | `int` | `10` | Maximum agents that can be spawned per workflow execution |
| `allow_recursive_orchestrators` | `bool` | `false` | Whether spawned agents can themselves be orchestrators |
| `delegation_timeout_seconds` | `int` | `300` | Max time for a single delegation to complete |
| `budget_policy` | `str` | `"inherit_parent"` | How cost/token budgets propagate: `inherit_parent`, `fixed`, `unlimited` |

### Global Configuration

Add to `HiveFlowConfig`:

```python
# Dynamic collaboration defaults
COLLABORATION_ENABLED: bool = False
COLLABORATION_MAX_DEPTH: int = 3
COLLABORATION_MAX_SPAWNED: int = 10
COLLABORATION_TIMEOUT: int = 300
```

Team-level settings override global defaults.

---

## Event Types

New events emitted during dynamic collaboration:

| Event Type | Data | Description |
|---|---|---|
| `agent_spawned` | `agent_id`, `archetype`, `spawned_by` | A new agent was created at runtime |
| `delegation_started` | `task`, `delegate_to`, `delegated_by`, `depth` | A sub-task was delegated to an agent |
| `delegation_completed` | `task`, `delegate_to`, `delegated_by`, `result_summary` | A delegated task completed |
| `delegation_failed` | `task`, `delegate_to`, `error` | A delegated task failed |
| `message_sent` | `from`, `to`, `subject` | An inter-agent message was sent |
| `plan_created` | `orchestrator_id`, `sub_task_count` | A task plan was generated |

These integrate with the existing `StreamChannel` and callback system
(see [02-workflows — Event Streaming](02-workflows.md)).

---

## Relationship to Existing Features

### vs. Sub-Workflows (02-workflows)

Sub-workflows are **statically defined** in the team config — a workflow step
references another `TeamConfiguration` by name. Dynamic delegation is
**runtime-decided** — an agent chooses what to delegate and to whom during
execution.

They are complementary:
- Use **sub-workflows** when the decomposition is known at design time
- Use **dynamic delegation** when the decomposition depends on runtime data

Implementation note: `DelegateTaskTool` can internally leverage the
sub-workflow machinery (loading a `TeamConfiguration` from the `TeamLibrary`
and executing it via a nested `WorkflowEngine`) when delegating to a full
sub-team rather than a single agent.

### vs. Parallel Fan-Out (02-workflows)

Parallel fan-out splits work across copies of the **same agent** processing
different data items. Dynamic delegation assigns **different tasks** to
**different specialists**. Fan-out is data-parallel; delegation is
task-parallel.

### vs. LLM-Generated Teams (03-agents-and-teams)

LLM team generation happens **once, before execution**, producing a static
config. Dynamic spawning happens **during execution**, adapting the team as
the problem unfolds. A generated team could include orchestrator agents
with collaboration enabled, combining both approaches.

### vs. Workflow-as-Agent Pattern (02-workflows)

The Phase 2 `workflow.as_agent()` pattern wraps a complete workflow to behave
as a single agent. Dynamic delegation is the inverse: an agent dynamically
creates and runs a workflow. Together they enable full hierarchical composition.

---

## Implementation Phases

### Phase 1 — Core Delegation and Spawning

**Prerequisites:** Existing `Agent`, `ToolPlugin`, `ArchetypeLibrary`, and
`WorkflowEngine` classes.

**Deliverables:**
1. `DelegateTaskTool` — tool plugin implementing single-agent delegation
2. `SpawnAgentTool` — tool plugin for runtime agent creation from archetypes
3. `CollaborationRuntime` — manages the runtime agent pool, depth tracking,
   and budget enforcement
4. `collaboration` config section in `TeamConfiguration` schema
5. Auto-injection of collaboration tools into orchestrator agents when
   `collaboration.enabled` is true
6. New event types: `agent_spawned`, `delegation_started`,
   `delegation_completed`, `delegation_failed`
7. Unit tests for all new components + integration test with a 2-level
   delegation scenario

### Phase 2 — Messaging and Multi-Agent Delegation

**Prerequisites:** Phase 1 complete.

**Deliverables:**
1. `MessageTool` (`send_message` + `read_messages`) — inter-agent messaging
   via state
2. Message injection into agent context assembly (`_summarize_state`)
3. Sub-team delegation — `DelegateTaskTool` supports delegating to a
   dynamically composed mini-workflow (multiple agents, not just one)
4. Parallel sub-task execution in the planner pattern
5. New event types: `message_sent`, `plan_created`

### Phase 3 — Adaptive Planning and Advanced Patterns

**Prerequisites:** Phase 2 complete.

**Deliverables:**
1. `CollaborativePlannerArchetype` — a reusable archetype with the planning
   system prompt and tool configuration pre-wired
2. Plan-and-execute loop with dependency resolution and parallel dispatch
3. Adaptive re-planning: if a sub-task fails or returns low-quality results,
   the planner can revise the plan and re-delegate
4. Delegation history and analytics (which agents were spawned, delegation
   success rates, cost breakdown per sub-task)
5. Example team configs demonstrating dynamic collaboration patterns

---

## Safety and Guardrails

### Recursion Protection

| Guard | Mechanism |
|---|---|
| **Depth limit** | `max_delegation_depth` prevents infinite delegation chains. Each delegation increments a `_delegation_depth` counter in the sub-state. Tools refuse to delegate when the limit is reached. |
| **Agent count limit** | `max_spawned_agents` caps the total number of runtime-spawned agents per workflow execution. |
| **Timeout** | `delegation_timeout_seconds` kills delegations that exceed the time limit. |
| **No self-delegation** | An agent cannot delegate to itself (cycle detection). |

### Budget Control

Spawned agents and delegated tasks consume resources (LLM tokens, tool calls,
wall-clock time). Budget policies control this:

| Policy | Behavior |
|---|---|
| `inherit_parent` | Child inherits remaining budget from parent. Parent's budget is reduced by child's consumption. |
| `fixed` | Each child gets a fixed budget (configurable). Parent budget is reserved upfront. |
| `unlimited` | No budget enforcement on children (use with caution). |

Budget tracking integrates with the existing `CostTracker` in
`ResilientLLMProvider` (see `core/cost.py` and `core/resilient_provider.py`).

### Audit Trail

All collaboration actions are recorded in an audit-trail-compatible format:

```json
{
  "event": "delegation_completed",
  "orchestrator_id": "planner",
  "delegate_id": "spawned_researcher_0",
  "task": "Research competitor pricing",
  "depth": 1,
  "duration_ms": 4500,
  "tokens_used": 2300,
  "result_summary": "Found pricing data for 5 competitors..."
}
```

---

## Example Scenarios

### Scenario 1: Adaptive Research

```
User task: "Analyze the competitive landscape for AI code assistants"

1. Orchestrator receives task
2. Calls spawn_agent(archetype="researcher") → spawned_researcher_0
3. Calls spawn_agent(archetype="researcher") → spawned_researcher_1
4. Calls delegate_task(task="Research GitHub Copilot features and pricing",
                       delegate_to="spawned_researcher_0")
5. Calls delegate_task(task="Research Cursor and Windsurf features and pricing",
                       delegate_to="spawned_researcher_1")
6. Collects both results
7. Calls spawn_agent(archetype="writer") → spawned_writer_0
8. Calls delegate_task(task="Write competitive analysis report using this data: ...",
                       delegate_to="spawned_writer_0")
9. Returns the final report
```

### Scenario 2: Dynamic Expertise Recruitment

```
User task: "Review this contract for legal and financial risks"

1. Orchestrator receives task
2. Analyzes the document — identifies legal clauses and financial terms
3. Calls spawn_agent(custom_definition={
       role: "Legal Analyst",
       system_prompt: "You are an expert in contract law...",
       behavior_type: "llm_only"
   }) → spawned_legal_0
4. Calls spawn_agent(custom_definition={
       role: "Financial Analyst",
       system_prompt: "You are an expert in financial risk...",
       behavior_type: "llm_only"
   }) → spawned_financial_0
5. Delegates legal clause review to spawned_legal_0
6. Delegates financial term review to spawned_financial_0
7. Synthesizes both analyses into a unified risk assessment
```

### Scenario 3: Iterative Delegation with Feedback

```
User task: "Write a technical blog post about quantum computing"

1. Orchestrator delegates research to existing researcher agent
2. Researcher returns findings
3. Orchestrator evaluates: findings are too shallow on error correction
4. Orchestrator delegates again: "Deep dive into quantum error correction,
   specifically surface codes and their current limitations"
5. Researcher returns deeper findings
6. Orchestrator delegates writing to writer agent with both research results
7. Writer returns draft
8. Orchestrator sends message to reviewer: "Please review this draft for
   technical accuracy"
9. Reviewer returns feedback via message
10. Orchestrator delegates revision to writer with reviewer feedback
11. Returns final post
```

---

## Testing Strategy

### Unit Tests

- `DelegateTaskTool`: delegation to existing agent, delegation with auto-resolve,
  delegation depth limit enforcement, timeout enforcement
- `SpawnAgentTool`: spawn from archetype, spawn from inline definition, spawn
  limit enforcement, invalid archetype handling
- `MessageTool`: send message, broadcast message, read messages, unread
  filtering
- `CollaborationRuntime`: agent pool management, depth tracking, budget
  enforcement, concurrent access

### Integration Tests

- Two-level delegation: orchestrator → spawned researcher → result → orchestrator
- Parallel delegation: orchestrator delegates 3 tasks concurrently, collects
  all results
- Full planning cycle: orchestrator plans, spawns agents, delegates, collects,
  synthesizes
- Budget exhaustion: delegation stops when budget is consumed
- Depth limit: delegation chain terminates cleanly at max depth

### Example Configs

Provide ready-to-use team templates demonstrating:
- `adaptive_research.json` — orchestrator with dynamic research delegation
- `collaborative_review.json` — multi-reviewer with messaging for consensus
- `expert_panel.json` — dynamic expert recruitment for complex analysis

---

[< Back to Index](README.md)
