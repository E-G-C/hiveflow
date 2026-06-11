# Quickstart: Core Architecture

**Feature**: 001-core-architecture
**Date**: 2026-02-22

## Minimal Usage Examples

These examples demonstrate the target developer experience after implementation. They serve as acceptance tests for API ergonomics (SC-001, SC-002).

### 1. Single Agent Execution (< 10 lines — SC-001)

```python
from hiveflow import HiveFlow

hf = HiveFlow()
session = hf.run_sync(
    team={"team_name": "single", "description": "One agent", "agents": [
        {"id": "writer", "role": "Writer", "system_prompt": "Write clearly.", "behavior_type": "llm_only"}
    ], "workflow": {"steps": [{"agent": "writer", "type": "sequential"}]}},
    task="Write a haiku about Python",
)
print(session.result.state["writer_output"])
```

### 2. Template-Based Team (< 5 lines — SC-002)

```python
from hiveflow import HiveFlow

hf = HiveFlow()
session = hf.run_sync(team="summarizer", task="Summarize the history of computing")
print(session.result.state)
```

### 3. Async Execution with Events

```python
import asyncio
from hiveflow import HiveFlow

async def main():
    hf = HiveFlow()
    session = await hf.run(team="researcher", task="Research quantum computing")

    async for event in session.subscribe():
        print(f"[{event.event_type}] {event.agent_id}: {event.data}")

    print(session.result.state)

asyncio.run(main())
```

### 4. Human-in-the-Loop with Checkpoint Resume

```python
import asyncio
from hiveflow import HiveFlow
from hiveflow.core.checkpoint import FileCheckpointStorage

async def main():
    hf = HiveFlow(checkpoint_storage=FileCheckpointStorage())

    # Start workflow — pauses at human gate
    session = await hf.run(team="review_team", task="Draft a proposal", checkpoint=True)

    if session.status.value == "paused":
        for req in session.pending_requests:
            print(f"Approval needed: {req.context}")

        # Resume with approval (even after process restart)
        session = await hf.resume(
            session_id=session.session_id,
            responses={req.request_id: {"approved": True, "feedback": "Looks good"}},
        )

    print(session.result.state)

asyncio.run(main())
```

### 5. Action Executor with Safety Policy

```python
from hiveflow import HiveFlow

hf = HiveFlow()
session = hf.run_sync(
    team={"team_name": "action_team", "description": "Agent that sends emails",
          "agents": [
              {"id": "emailer", "role": "Email Sender", "behavior_type": "action_executor",
               "system_prompt": "Send emails as instructed.", "tools": ["send_email"],
               "action_policy": "require_approval"}
          ],
          "workflow": {"steps": [{"agent": "emailer", "type": "sequential"}]}},
    task="Send a welcome email to new-user@example.com",
)

# Session pauses for action approval
if session.status.value == "paused":
    for req in session.pending_requests:
        print(f"Proposed action: {req.context}")
```

### 6. LLM-Generated Team

```python
import asyncio
from hiveflow import HiveFlow

async def main():
    hf = HiveFlow()
    result = await hf.generate_team(task="Analyze competitor pricing strategies")

    print(f"Team: {result.config.team_name}")
    print(f"Agents: {[a.id for a in result.config.agents]}")

    if result.has_blocking_gaps:
        print(f"Blocking gaps: {[g.resource_id for g in result.capability_gaps]}")
    else:
        session = await hf.run(team=result.config, task="Analyze competitor pricing")
        print(session.result.state)

asyncio.run(main())
```

### 7. Discovery APIs

```python
from hiveflow import HiveFlow

hf = HiveFlow()
print("Teams:", hf.team_library().list_templates())
print("Archetypes:", hf.archetype_library().list_archetypes())
print("Tools:", [t.plugin_id for t in hf.tool_registry().list_plugins()])
```

### 8. Custom Team with Gated Step

```python
from hiveflow import HiveFlow

hf = HiveFlow()
session = hf.run_sync(
    team={"team_name": "gated_flow", "description": "Flow with a gate",
          "agents": [
              {"id": "drafter", "role": "Drafter", "system_prompt": "Draft content.",
               "behavior_type": "llm_only"},
              {"id": "publisher", "role": "Publisher", "system_prompt": "Publish content.",
               "behavior_type": "action_executor", "tools": ["publish"],
               "action_policy": "auto"},
          ],
          "workflow": {"steps": [
              {"agent": "drafter", "type": "sequential", "next": "approval_gate"},
              {"agent": "", "type": "gated", "gate_id": "approval_gate",
               "gate_description": "Review draft before publishing", "next": "publisher"},
              {"agent": "publisher", "type": "sequential"},
          ]}},
    task="Write and publish a blog post about AI safety",
)
```
