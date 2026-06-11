# Quickstart: Agents and Teams

**Feature**: 005-agents-and-teams
**Date**: 2026-02-24

This document shows how to verify the agents and teams feature works end-to-end after implementation.

---

## Scenario 1: Define and Run a Team (P1 — Core)

Create a team config and run it.

**team_config.json**:
```json
{
  "team_name": "simple_team",
  "version": "1.0",
  "description": "A simple two-agent team for testing",
  "agents": [
    {
      "id": "researcher",
      "role": "Researcher",
      "system_prompt": "You research the given topic and provide key findings.",
      "behavior_type": "llm_only"
    },
    {
      "id": "writer",
      "role": "Writer",
      "system_prompt": "You write a summary based on the research findings.",
      "behavior_type": "llm_only"
    }
  ],
  "workflow": {
    "steps": [
      { "agent": "researcher", "type": "sequential", "next": "writer" },
      { "agent": "writer", "type": "sequential", "next": null }
    ]
  }
}
```

**Run via CLI**:
```bash
hiveflow run --team team_config.json --query "Summarize recent advances in quantum computing"
```

**Run via Python SDK**:
```python
from hiveflow import HiveFlow

hf = HiveFlow()
result = await hf.run(team="team_config.json", task="Summarize recent advances in quantum computing")
print(result.final_output)
```

**Expected**: Both agents execute sequentially. Researcher output feeds writer. Final output is a summary.

---

## Scenario 2: Use Archetypes (P2)

Compose a team from the archetype library.

```python
from hiveflow.core.teams import ArchetypeLibrary, TeamGenerator

# Load built-in archetypes (now from templates/archetypes/*.json)
lib = ArchetypeLibrary.default()
print(lib.list_archetypes())
# → ['researcher', 'planner', 'writer', 'reviewer', 'editor', 'human_reviewer']

# Get a specific archetype
researcher = lib.get("researcher")
print(researcher["role"])  # → "Deep Researcher"

# Generate a team using the template-based generator
gen = TeamGenerator(archetype_library=lib)
config = gen.generate_team(task_description="Write a research report", include_review=True)
print(config["team_name"])
```

**Expected**: All 6 archetypes load from JSON files. Team generates with inline agent definitions.

---

## Scenario 3: Action Executor with Safety Policies (P2)

Test each action policy including new dry_run.

**team_with_actions.json** (excerpt):
```json
{
  "agents": [
    {
      "id": "deployer",
      "role": "Deployment Agent",
      "system_prompt": "You execute deployment operations.",
      "behavior_type": "action_executor",
      "tools": ["cloud_deploy"],
      "action_policy": "dry_run"
    }
  ],
  "workflow": {
    "steps": [
      { "agent": "deployer", "type": "sequential", "next": null }
    ]
  }
}
```

**Verify dry_run**:
```python
result = await hf.run(team="team_with_actions.json", task="Deploy to staging")
# Dry run plan recorded, no actual execution
assert "deployer_dry_run_plan" in result.state
assert len(result.state["deployer_dry_run_plan"]) > 0
```

**Verify require_approval pauses**:
Change `action_policy` to `"require_approval"` and verify workflow pauses with a checkpoint.

**Verify audit trail enhancement**:
```python
records = result.state.get("deployer_action_records", [])
for record in records:
    assert "policy" in record       # NEW
    assert "agent_id" in record
    assert "reversible" in record   # NEW
```

---

## Scenario 4: Conditional with Reject Default (P2)

Test that ambiguous results default to reject path.

```json
{
  "agents": [
    { "id": "writer", "role": "Writer", "system_prompt": "Write content.", "behavior_type": "llm_only" },
    { "id": "reviewer", "role": "Reviewer", "system_prompt": "Review content.", "behavior_type": "llm_only" },
    { "id": "reviser", "role": "Reviser", "system_prompt": "Revise the content.", "behavior_type": "llm_only" }
  ],
  "workflow": {
    "steps": [
      { "agent": "writer", "type": "sequential", "next": "reviewer" },
      { "agent": "reviewer", "type": "conditional", "next_on_accept": null, "next_on_reject": "reviser", "max_iterations": 2 },
      { "agent": "reviser", "type": "sequential", "next": "reviewer" }
    ]
  }
}
```

**Expected**: When reviewer output is ambiguous, workflow goes to reviser (reject path). Stops after max_iterations=2 cycles.

---

## Scenario 5: on_failure Agent Policy (FR-020)

```json
{
  "agents": [
    {
      "id": "flaky_agent",
      "role": "Flaky Agent",
      "system_prompt": "You sometimes fail.",
      "behavior_type": "llm_only",
      "on_failure": "retry",
      "max_retries": 2
    },
    {
      "id": "backup",
      "role": "Backup",
      "system_prompt": "You provide backup output.",
      "behavior_type": "llm_only"
    }
  ],
  "workflow": {
    "steps": [
      { "agent": "flaky_agent", "type": "sequential", "next": "backup" },
      { "agent": "backup", "type": "sequential", "next": null }
    ]
  }
}
```

**Expected**: If flaky_agent fails, it retries up to 2 times. If still fails, workflow halts. With `on_failure: "skip"`, workflow proceeds to backup.

---

## Scenario 6: Transient LLM Error Backoff (FR-021)

```python
# This scenario verifies the transparent backoff layer.
# When an LLM returns 429 (rate limit), the system retries with
# exponential backoff (1s, 2s, 4s) before considering it a failure.

# In test: mock the LLM to return 429 twice, then succeed.
# The agent should complete successfully with no on_failure triggered.
# Structured logs should show 2 retry attempts with backoff delays.
```

**Expected**: Transient 429/5xx errors are retried up to 3 times with exponential backoff. Only persistent failures reach the `on_failure` policy.

---

## Scenario 7: Gated Step with Checkpoint (P2)

```json
{
  "agents": [
    { "id": "planner", "role": "Planner", "system_prompt": "Plan the work.", "behavior_type": "llm_only" },
    { "id": "executor", "role": "Executor", "system_prompt": "Execute the plan.", "behavior_type": "llm_only" }
  ],
  "workflow": {
    "steps": [
      { "agent": "planner", "type": "sequential", "next": "executor" },
      { "agent": "executor", "type": "gated", "gate": "human_approval", "next": null }
    ]
  }
}
```

**Run with checkpoint**:
```python
result = await hf.run(team="gated_team.json", task="Plan and execute", checkpoint=True)
assert result.status == "paused"

result = await hf.resume(session_id=result.session_id, approvals={"executor": "approved"})
assert result.status == "completed"
```

---

## Validation Checklist

| # | Scenario | Validates |
|---|----------|-----------|
| 1 | Define and run team | FR-001, FR-002, SC-001 |
| 2 | Archetype library | FR-009, FR-010, SC-004, SC-010 |
| 3 | Action policies (dry_run) | FR-003, FR-004, SC-005 |
| 4 | Conditional reject default | Clarif. Q2, FR-022 |
| 5 | on_failure policy | FR-020 |
| 6 | Transient error backoff | FR-021, Constitution §2.7 |
| 7 | Gated step + checkpoint | FR-008, SC-006 |
