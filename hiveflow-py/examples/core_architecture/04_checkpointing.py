#!/usr/bin/env python3
"""Example: Workflow checkpointing -- persist paused workflows across restarts.

Demonstrates how to:
1. Create a FileCheckpointStorage for durable persistence
2. Save a WorkflowCheckpoint with full state
3. Load a checkpoint and verify round-trip fidelity
4. Save multiple checkpoints per session (accumulation)
5. List checkpoints for a session, ordered by creation time
6. Load a specific checkpoint by checkpoint_id (rewind)
7. List and delete checkpointed sessions

Checkpointing enables human-in-the-loop workflows that survive process
restarts: a workflow pauses at a gate, the checkpoint is written to disk,
and the workflow is resumed (possibly days later) from the saved state.

Each pause point produces a separate checkpoint, building a timeline
that can be inspected and rewound to any previous state.
"""

import asyncio
import time
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    FileCheckpointStorage,
    WorkflowCheckpoint,
)


async def main() -> None:
    """Demonstrate checkpoint save/load/list/delete lifecycle with accumulation."""
    print("Workflow Checkpointing Example")
    print("=" * 60)

    # Use a temporary directory (in production: ".hiveflow/checkpoints")
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileCheckpointStorage(directory=tmpdir)

        # -- Save a checkpoint (simulating a paused workflow) -------------------
        checkpoint = WorkflowCheckpoint(
            session_id="session-abc-123",
            step_index=2,  # Paused after step 2
            state={
                "task": "Analyze competitor pricing",
                "researcher_output": "Found 5 competitors with pricing data...",
                "pending_gate_id": "review_gate",
                "awaiting_gate_approval": True,
            },
            current_agent_id="review_gate",
            current_step_type="gated",
            pending_requests=[{
                "request_id": "req-001",
                "request_type": "gate",
                "context": {"gate_id": "review_gate"},
            }],
            iteration_counts={"reviewer": 1},
            task="Analyze competitor pricing",
        )

        checkpoint_id_1 = await storage.save(checkpoint)
        print(f"1. Saved checkpoint for session: {checkpoint.session_id}")
        print(f"   Checkpoint ID: {checkpoint_id_1}")
        print(f"   Step index: {checkpoint.step_index}")
        print(f"   Agent: {checkpoint.current_agent_id}")
        print(f"   State keys: {list(checkpoint.state.keys())}")

        # -- Serialize to dict (for inspection) ---------------------------------
        data = checkpoint.to_dict()
        print(f"\n2. Checkpoint dict keys: {list(data.keys())}")
        print(f"   Version: {data['version']}")

        # -- Load the checkpoint (simulating a process restart) -----------------
        loaded = await storage.load("session-abc-123")
        assert loaded is not None
        print(f"\n3. Loaded latest checkpoint: {loaded.session_id}")
        print(f"   Checkpoint ID: {loaded.checkpoint_id}")
        print(f"   Step index: {loaded.step_index}")
        print(f"   Task: {loaded.task}")
        print(f"   State matches: {loaded.state == checkpoint.state}")

        # -- Checkpoint accumulation: save more for the same session ------------
        # Each pause point in a workflow produces a new checkpoint,
        # building a history that can be inspected or rewound.
        time.sleep(0.01)  # Ensure distinct created_at timestamps
        checkpoint_2 = WorkflowCheckpoint(
            session_id="session-abc-123",
            step_index=3,
            state={
                "task": "Analyze competitor pricing",
                "researcher_output": "Found 5 competitors with pricing data...",
                "review_approved": True,
                "pending_gate_id": "deploy_gate",
                "awaiting_gate_approval": True,
            },
            current_agent_id="deploy_gate",
            current_step_type="gated",
            task="Analyze competitor pricing",
        )
        checkpoint_id_2 = await storage.save(checkpoint_2)
        print(f"\n4. Saved second checkpoint (same session)")
        print(f"   Checkpoint ID: {checkpoint_id_2}")
        print(f"   Step index: {checkpoint_2.step_index}")
        print(f"   Agent: {checkpoint_2.current_agent_id}")

        # -- List all checkpoints for a session (ordered by created_at) ---------
        checkpoints = await storage.list_checkpoints("session-abc-123")
        print(f"\n5. Checkpoints for session (oldest first): {len(checkpoints)}")
        for i, cp in enumerate(checkpoints):
            print(f"   [{i}] id={cp.checkpoint_id[:12]}... "
                  f"step={cp.step_index} agent={cp.current_agent_id}")

        # -- Load a specific checkpoint by ID (rewind) --------------------------
        rewound = await storage.load("session-abc-123", checkpoint_id_1)
        assert rewound is not None
        print(f"\n6. Rewound to specific checkpoint: {checkpoint_id_1[:12]}...")
        print(f"   Step index: {rewound.step_index}")
        print(f"   Agent: {rewound.current_agent_id}")
        print(f"   Still at gate: {rewound.state.get('awaiting_gate_approval')}")

        # -- Load nonexistent checkpoint_id returns None -------------------------
        missing = await storage.load("session-abc-123", "nonexistent-id")
        print(f"\n7. Load nonexistent checkpoint_id: {missing}")

        # -- List all sessions --------------------------------------------------
        await storage.save(WorkflowCheckpoint(
            session_id="session-def-456",
            step_index=0,
            state={"task": "another workflow"},
        ))

        sessions = await storage.list_sessions()
        print(f"\n8. Checkpointed sessions: {sorted(sessions)}")

        # -- Delete all checkpoints for a session --------------------------------
        await storage.delete("session-abc-123")
        remaining = await storage.list_sessions()
        print(f"9. After deletion: {sorted(remaining)}")

        # -- Verify deletion cleared all checkpoints ----------------------------
        checkpoints_after = await storage.list_checkpoints("session-abc-123")
        print(f"   Checkpoints remaining: {len(checkpoints_after)}")

    print("\nDone. In production, use FileCheckpointStorage('.hiveflow/checkpoints')")
    print("to persist across process restarts.")


if __name__ == "__main__":
    asyncio.run(main())
