#!/usr/bin/env python3
"""Example: WorkflowSession lifecycle -- status tracking, serialization, events.

Demonstrates how to:
1. Create a WorkflowSession and observe its status transitions
2. Work with ApprovalRequest objects
3. Serialize a session to JSON via to_dict()
4. Subscribe to event streams
5. Cancel a running or paused session

WorkflowSession is the handle returned by HiveFlow.run(). It provides a
stable identity, status tracking, and access to results and approval requests.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    ApprovalRequest,
    WorkflowSession,
    WorkflowStatus,
)
from hiveflow.core.workflow import WorkflowResult


async def main() -> None:
    """Walk through WorkflowSession lifecycle."""
    print("WorkflowSession Lifecycle Example")
    print("=" * 60)

    # -- Create a session -------------------------------------------------------
    session = WorkflowSession(task="Write and publish a blog post")

    print(f"1. New session created")
    print(f"   Session ID: {session.session_id}")
    print(f"   Status: {session.status.value}")
    print(f"   Result: {session.result}")
    print(f"   Pending requests: {session.pending_requests}")

    # -- Simulate RUNNING status ------------------------------------------------
    session._set_status(WorkflowStatus.RUNNING)
    print(f"\n2. Status -> {session.status.value}")

    # -- Simulate PAUSED with pending approval ----------------------------------
    paused_result = WorkflowResult(
        status=WorkflowStatus.PAUSED,
        state={
            "task": "Write and publish a blog post",
            "drafter_output": "Here is the draft...",
            "awaiting_gate_approval": True,
            "pending_gate_id": "review_gate",
            "pending_gate_description": "Review draft before publishing",
        },
    )
    session._set_result(paused_result)
    print(f"\n3. Status -> {session.status.value}")
    print(f"   Pending requests: {len(session.pending_requests)}")
    for req in session.pending_requests:
        print(f"     Type: {req.request_type}")
        print(f"     Context: {req.context}")

    # -- Serialize to JSON (e.g., for a REST API response) ----------------------
    snapshot = session.to_dict()
    print(f"\n4. JSON serialization:")
    print(f"   {json.dumps(snapshot, indent=2, default=str)[:500]}...")

    # -- Resume from PAUSED state -----------------------------------------------
    await session.resume({"approval": True, "feedback": "Looks great"})
    print(f"\n5. After resume: status -> {session.status.value}")
    print(f"   Pending requests cleared: {len(session.pending_requests) == 0}")

    # -- Demonstrate cancel -----------------------------------------------------
    session2 = WorkflowSession(task="Another workflow")
    session2._set_status(WorkflowStatus.RUNNING)
    await session2.cancel()
    print(f"\n6. Cancelled session: status -> {session2.status.value}")
    print(f"   Error: {session2.error}")

    # -- ApprovalRequest standalone demo ----------------------------------------
    print(f"\n7. ApprovalRequest:")
    req = ApprovalRequest(
        request_type="action_approval",
        context={"proposed_actions": [{"tool": "send_email", "to": "user@example.com"}]},
        agent_id="emailer",
        step_index=1,
    )
    d = req.to_dict()
    print(f"   to_dict keys: {list(d.keys())}")

    restored = ApprovalRequest.from_dict(d)
    print(f"   Round-trip: request_type={restored.request_type}, agent_id={restored.agent_id}")

    # -- Event streaming --------------------------------------------------------
    print(f"\n8. Event streaming:")
    session3 = WorkflowSession(task="test")
    consumer = session3.subscribe()
    print(f"   Subscribed to event stream (consumer type: {type(consumer).__name__})")
    print("   In async workflows, iterate: async for event in session.subscribe(): ...")


if __name__ == "__main__":
    asyncio.run(main())
