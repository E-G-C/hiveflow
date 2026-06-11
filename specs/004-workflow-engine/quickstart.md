# Quickstart: Workflow Engine Checkpoint & Resume

**Feature**: 004-workflow-engine

This guide shows how to use workflow checkpointing and resume in HiveFlow.

## Prerequisites

- HiveFlow installed with core dependencies
- A team configuration with at least one gated or human_gate step

## 1. Enable Checkpointing on a Workflow Run

```python
from hiveflow import HiveFlow
from hiveflow.core.checkpoint import FileCheckpointStorage

# Create HiveFlow with checkpoint storage
hf = HiveFlow(
    checkpoint_storage=FileCheckpointStorage(".hiveflow/checkpoints")
)

# Run a workflow with checkpointing enabled
session = await hf.run(
    team="incident-response",
    task="Investigate API latency spike",
    checkpoint=True,
)

# If the workflow has a gate, it will pause
if session.status == "paused":
    print(f"Workflow paused at gate. Session: {session.session_id}")
    print(f"Pending requests: {session.pending_requests}")
```

## 2. List Available Checkpoints

```python
# List all checkpoints for a session
checkpoints = await hf.list_checkpoints(session.session_id)

for cp in checkpoints:
    print(f"  Checkpoint: {cp['checkpoint_id']}")
    print(f"  Step: {cp['current_agent_id']} (index {cp['step_index']})")
    print(f"  Created: {cp['created_at']}")
```

## 3. Resume a Paused Workflow

```python
# Get the pending approval request
request = session.pending_requests[0]

# Resume with approval
session = await hf.resume(
    session_id=session.session_id,
    responses={request.request_id: "approved"},
)

print(f"Workflow completed with status: {session.status}")
```

## 4. Resume from a Specific Checkpoint (Rewind)

```python
# Resume from an earlier checkpoint instead of the latest
session = await hf.resume(
    session_id=session.session_id,
    responses={"req-123": "approved"},
    checkpoint_id="550e8400-e29b-41d4-a716-446655440000",
)
```

## 5. Monitor Events During Execution

```python
# Register event callbacks before running
hf_engine = ...  # obtained from build()

hf_engine.on_event(lambda event_type, agent_id, data:
    print(f"[{event_type}] {agent_id}: {data}")
)

# Events emitted during resume:
# [approval] deploy_gate: {"request_id": "req-123", "decision": "approved"}
# [step_start] deployer: {"step_index": 3}
# [step_complete] deployer: {"step_index": 3}
# [checkpoint_saved] deployer: {"checkpoint_id": "...", "step_index": 3}
# [output] : {"result": "Deployment complete"}
```

## 6. Team Configuration with Gates

Example team config that triggers checkpointing:

```yaml
team_name: "incident-response"
description: "Automated incident response with human approval"
agents:
  - id: investigator
    role: "Incident Investigator"
    system_prompt: "Investigate the incident..."
    behavior_type: tool_user
    tools: [log_query, metrics_dashboard]

  - id: approval
    role: "Human Approval Gate"
    system_prompt: "Present findings for approval"
    behavior_type: human_gate

  - id: remediator
    role: "Remediator"
    system_prompt: "Execute remediation actions..."
    behavior_type: action_executor
    action_policy: require_approval

workflow:
  steps:
    - agent: investigator
      type: sequential
      next: approval

    - agent: approval
      type: human_gate
      next: remediator

    - agent: remediator
      type: sequential
```

When this workflow runs with `checkpoint=True`, it will:
1. Execute `investigator` (sequential)
2. Pause at `approval` (human_gate) — **checkpoint saved automatically**
3. After resume with approval: execute `remediator`
4. If remediator requires action approval — **another checkpoint saved**
5. After second resume: complete

## Error Handling

```python
from hiveflow.core.checkpoint import CheckpointError

try:
    session = await hf.resume(session_id="old-session", responses={})
except KeyError:
    print("Session not found")
except CheckpointError as e:
    print(f"Checkpoint invalid: {e}")
except ValueError as e:
    print(f"Cannot resume: {e}")  # e.g., workflow is FAILED, not PAUSED
```
