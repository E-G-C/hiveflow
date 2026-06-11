#!/usr/bin/env python3
"""MCP Integration 07: Checkpoint Cold-Resume.

Demonstrates how to:
  1. Save a checkpoint with team_config and task
  2. Load and inspect checkpoint data
  3. Round-trip through serialization (to_dict / from_dict)
  4. Handle backward compatibility with old checkpoint formats
  5. Simulate a cold-resume scenario (process restart)

No MCP servers or API keys required -- uses FileCheckpointStorage
with a temporary directory.

Usage:
    uv run python examples/mcp_integration/07_checkpoint_cold_resume.py
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.checkpoint import (
    FileCheckpointStorage,
    WorkflowCheckpoint,
)


# ---------------------------------------------------------------------------
# Sample team config (would come from a YAML/JSON team definition)
# ---------------------------------------------------------------------------

TEAM_CONFIG = {
    "name": "approval_flow",
    "description": "Multi-step approval workflow",
    "agents": [
        {
            "id": "drafter",
            "role": "Document drafter",
            "system_prompt": "Draft documents based on requirements.",
            "behavior_type": "llm_only",
        },
        {
            "id": "reviewer",
            "role": "Document reviewer",
            "system_prompt": "Review documents for quality and accuracy.",
            "behavior_type": "llm_only",
        },
    ],
    "workflow": {
        "steps": [
            {"type": "sequential", "agent": "drafter", "next_step": "approval_gate"},
            {"type": "gated", "agent": "approval_gate", "gate_id": "approve_draft"},
            {"type": "sequential", "agent": "reviewer"},
        ],
    },
}


# ---------------------------------------------------------------------------
# 1. Save checkpoint with team_config and task
# ---------------------------------------------------------------------------

async def demo_save_checkpoint() -> None:
    """Create and save a checkpoint containing team_config and task."""
    print("1. Saving Checkpoint with team_config and task")
    print("-" * 50)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileCheckpointStorage(directory=tmpdir)

        checkpoint = WorkflowCheckpoint(
            session_id="session-001",
            step_index=1,
            state={
                "task": "Draft the Q4 earnings report",
                "drafter_output": "## Q4 Earnings\n\nRevenue increased by 15%...",
                "awaiting_gate_approval": True,
            },
            current_agent_id="approval_gate",
            current_step_type="gated",
            team_config=TEAM_CONFIG,
            task="Draft the Q4 earnings report",
        )

        checkpoint_id = await storage.save(checkpoint)
        print(f"  Saved checkpoint: {checkpoint_id}")
        print(f"  Session ID:       {checkpoint.session_id}")
        print(f"  Step index:       {checkpoint.step_index}")
        print(f"  Task:             {checkpoint.task}")
        print(f"  Team config name: {checkpoint.team_config.get('name')}")
        print(f"  Agent count:      {len(checkpoint.team_config.get('agents', []))}")

        # Show the checkpoint file on disk
        files = list(Path(tmpdir).glob("*.json"))
        print(f"  File on disk:     {files[0].name}")
        print()


# ---------------------------------------------------------------------------
# 2. Load and inspect checkpoint
# ---------------------------------------------------------------------------

async def demo_load_checkpoint() -> None:
    """Load a checkpoint and verify team_config/task are present."""
    print("2. Loading Checkpoint")
    print("-" * 50)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileCheckpointStorage(directory=tmpdir)

        # Save
        original = WorkflowCheckpoint(
            session_id="session-002",
            step_index=1,
            state={"task": "Review the PR", "drafter_output": "Draft content..."},
            team_config=TEAM_CONFIG,
            task="Review the PR",
        )
        await storage.save(original)

        # Load
        loaded = await storage.load("session-002")

        print(f"  Loaded session:    {loaded.session_id}")
        print(f"  Task:              {loaded.task}")
        print(f"  Team config name:  {loaded.team_config.get('name')}")
        print(f"  Step index:        {loaded.step_index}")
        print(f"  State keys:        {list(loaded.state.keys())}")
        print(f"  Configs match:     {loaded.team_config == TEAM_CONFIG}")
        print()


# ---------------------------------------------------------------------------
# 3. Serialization round-trip
# ---------------------------------------------------------------------------

def demo_serialization() -> None:
    """Round-trip through to_dict / from_dict."""
    print("3. Serialization Round-Trip")
    print("-" * 50)

    original = WorkflowCheckpoint(
        session_id="session-003",
        step_index=2,
        state={"task": "Summarize findings", "output": "Summary here..."},
        team_config=TEAM_CONFIG,
        task="Summarize findings",
        pending_requests=[{"id": "gate-1", "type": "approval"}],
    )

    # Serialize to dict (as stored in JSON file)
    data = original.to_dict()
    print(f"  Serialized keys: {sorted(data.keys())}")
    print(f"  Has team_config: {'team_config' in data}")
    print(f"  Has task:        {'task' in data}")

    # Deserialize back
    restored = WorkflowCheckpoint.from_dict(data)
    print(f"  Restored task:   {restored.task}")
    print(f"  Configs match:   {restored.team_config == TEAM_CONFIG}")
    print(f"  Pending reqs:    {len(restored.pending_requests)}")

    # Full JSON round-trip
    json_str = json.dumps(data, indent=2)
    json_loaded = WorkflowCheckpoint.from_dict(json.loads(json_str))
    print(f"  JSON round-trip: {json_loaded.team_config == TEAM_CONFIG}")
    print()


# ---------------------------------------------------------------------------
# 4. Backward compatibility
# ---------------------------------------------------------------------------

def demo_backward_compat() -> None:
    """Old checkpoint formats (missing team_config/task) still load."""
    print("4. Backward Compatibility")
    print("-" * 50)

    # Simulate an old checkpoint format (pre-enhancement)
    old_data = {
        "session_id": "old-session-001",
        "step_index": 2,
        "state": {"key": "value", "task": "Old task from state"},
        "pending_requests": [],
        "iteration_counts": {},
        "created_at": 1700000000.0,
        "version": "1",
        # No team_config, no task fields
    }

    restored = WorkflowCheckpoint.from_dict(old_data)
    print(f"  Old format (no team_config, no task):")
    print(f"    session_id:  {restored.session_id}")
    print(f"    team_config: {restored.team_config}  (defaults to empty dict)")
    print(f"    task:        '{restored.task}'  (defaults to empty string)")
    print()

    # Partial old format (has task but no team_config)
    partial_data = {
        "session_id": "old-session-002",
        "step_index": 1,
        "state": {},
        "task": "Partial old task",
        # No team_config
    }

    restored2 = WorkflowCheckpoint.from_dict(partial_data)
    print(f"  Partial format (task but no team_config):")
    print(f"    task:        '{restored2.task}'")
    print(f"    team_config: {restored2.team_config}  (defaults to empty dict)")
    print()


# ---------------------------------------------------------------------------
# 5. Cold-resume scenario
# ---------------------------------------------------------------------------

async def demo_cold_resume() -> None:
    """Simulate a cold-resume: process restarts, loads from checkpoint only."""
    print("5. Cold-Resume Scenario")
    print("-" * 50)

    with tempfile.TemporaryDirectory() as tmpdir:
        # === First process: workflow pauses at a gate ===
        print("  --- Process 1: Workflow pauses at gate ---")
        storage = FileCheckpointStorage(directory=tmpdir)

        checkpoint = WorkflowCheckpoint(
            session_id="cold-resume-session",
            step_index=1,
            state={
                "task": "Generate quarterly report",
                "drafter_output": "## Q4 Report\n\nKey findings...",
                "awaiting_gate_approval": True,
            },
            current_agent_id="approval_gate",
            current_step_type="gated",
            team_config=TEAM_CONFIG,
            task="Generate quarterly report",
        )
        await storage.save(checkpoint)
        print(f"  Checkpoint saved for session: {checkpoint.session_id}")
        print(f"  Process 1 exits.")
        print()

        # === Second process: cold-resume from checkpoint ===
        print("  --- Process 2: Fresh start, cold-resume ---")

        # Simulating a brand new process -- no in-memory session
        fresh_storage = FileCheckpointStorage(directory=tmpdir)

        # Load the checkpoint
        loaded = await fresh_storage.load("cold-resume-session")
        if loaded is None:
            print("  ERROR: No checkpoint found!")
            return

        print(f"  Loaded checkpoint for: {loaded.session_id}")
        print(f"  Task (from checkpoint):        '{loaded.task}'")
        print(f"  Team config (from checkpoint): '{loaded.team_config.get('name')}'")
        print(f"  Step to resume from:           {loaded.step_index}")
        print()

        # The resume logic uses checkpoint data to rebuild the workflow
        # Priority: session._team_config (in-memory) > checkpoint.team_config
        session_config = None  # No in-memory config (cold start)

        if session_config is not None:
            config_used = session_config
            source = "session (in-memory)"
        elif loaded.team_config:
            config_used = loaded.team_config
            source = "checkpoint (cold-resume)"
        else:
            config_used = {}
            source = "default (empty)"

        print(f"  Config source:  {source}")
        print(f"  Config name:    {config_used.get('name', '(none)')}")
        print(f"  Agent count:    {len(config_used.get('agents', []))}")
        print()

        # List sessions with checkpoints
        sessions = await fresh_storage.list_sessions()
        print(f"  Sessions with checkpoints: {sessions}")

        # List all checkpoints for the session
        all_cps = await fresh_storage.list_checkpoints("cold-resume-session")
        print(f"  Checkpoints for session:   {len(all_cps)}")
        for cp in all_cps:
            print(f"    - checkpoint_id: {cp.checkpoint_id[:12]}... "
                  f"step: {cp.step_index}, task: '{cp.task}'")

    print()


# ---------------------------------------------------------------------------
# 6. Multiple checkpoints (accumulation)
# ---------------------------------------------------------------------------

async def demo_checkpoint_accumulation() -> None:
    """Show multiple checkpoints per session for history/rewind."""
    print("6. Checkpoint Accumulation")
    print("-" * 50)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileCheckpointStorage(directory=tmpdir)

        # Save checkpoints at different workflow stages
        for step_idx, agent_id in [(0, "drafter"), (1, "approval_gate"), (2, "reviewer")]:
            cp = WorkflowCheckpoint(
                session_id="multi-cp-session",
                step_index=step_idx,
                state={"task": "Multi-step workflow", "stage": agent_id},
                current_agent_id=agent_id,
                team_config=TEAM_CONFIG,
                task="Multi-step workflow",
            )
            await storage.save(cp)

        checkpoints = await storage.list_checkpoints("multi-cp-session")
        print(f"  Session: multi-cp-session")
        print(f"  Total checkpoints: {len(checkpoints)}")
        print()
        for cp in checkpoints:
            print(f"    Step {cp.step_index}: agent='{cp.current_agent_id}', "
                  f"id={cp.checkpoint_id[:8]}...")

        # Load latest (default behavior)
        latest = await storage.load("multi-cp-session")
        print()
        print(f"  Latest checkpoint: step {latest.step_index}, "
              f"agent='{latest.current_agent_id}'")

        # Load specific checkpoint
        target_id = checkpoints[0].checkpoint_id
        specific = await storage.load("multi-cp-session", checkpoint_id=target_id)
        print(f"  Specific (first):  step {specific.step_index}, "
              f"agent='{specific.current_agent_id}'")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- Checkpoint Cold-Resume")
    print("=" * 60)
    print()

    await demo_save_checkpoint()
    await demo_load_checkpoint()
    demo_serialization()
    demo_backward_compat()
    await demo_cold_resume()
    await demo_checkpoint_accumulation()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
