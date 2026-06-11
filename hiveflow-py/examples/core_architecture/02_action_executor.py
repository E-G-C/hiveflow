#!/usr/bin/env python3
"""Example: Action executor behavior type with safety policies.

Demonstrates how to:
1. Create an action_executor agent with the 'auto' policy (immediate execution + audit trail)
2. Create an action_executor agent with the 'require_approval' policy (pause for human approval)
3. Inspect proposed actions and audit records in the workflow state

This example uses mock providers and runs without API keys.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.core.workflow import StepType
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# -- Mock providers and tools ---------------------------------------------------

class MockToolPlugin:
    """Minimal tool that simulates sending an email."""

    def __init__(self):
        self.plugin_id = "send_email"

    def to_llm_tool_spec(self):
        return {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "Send an email",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                    },
                    "required": ["to"],
                },
            },
        }

    async def execute(self, args):
        return {"sent": True, "to": args.get("to", "unknown")}


class ToolCallingProvider(LLMProvider):
    """LLM that proposes a tool call, then returns a final response."""

    def __init__(self):
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock_tool_llm"

    @property
    def description(self) -> str:
        return "Mock LLM with tool calls"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self._call_count += 1
        if self._call_count == 1:
            return LLMResponse(
                content="I'll send the email now.",
                model="mock",
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "send_email",
                        "arguments": json.dumps({
                            "to": "new-hire@company.com",
                            "subject": "Welcome aboard!",
                        }),
                    },
                }],
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        return LLMResponse(
            content="Email sent successfully!",
            model="mock",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


# -- Example 1: Auto policy (execute immediately) ------------------------------

async def demo_auto_policy() -> None:
    """Action executor with auto policy -- tools run immediately with audit trail."""
    print("=" * 60)
    print("DEMO: action_executor with auto policy")
    print("=" * 60)

    agent = Agent(
        agent_id="emailer",
        role="Email Sender",
        system_prompt="Send emails as instructed.",
        behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
        tools=[MockToolPlugin()],
        llm_provider=ToolCallingProvider(),
        action_policy="auto",
    )

    steps = [WorkflowStep(agent="emailer", step_type=StepType.SEQUENTIAL)]
    engine = WorkflowEngine(steps)
    result = await engine.execute(
        {"emailer": agent},
        {"task": "Send a welcome email to new-hire@company.com"},
    )

    print(f"Status: {result.status.value}")
    print(f"Output: {result.state.get('emailer_output', '')}")

    # Inspect the structured audit trail
    records = result.state.get("emailer_action_records", [])
    print(f"\nAudit trail ({len(records)} action(s)):")
    for record in records:
        print(f"  Tool: {record['tool']}")
        print(f"  Args: {record['arguments']}")
        print(f"  Result: {record['result']}")
        print(f"  Status: {record['status']}")


# -- Example 2: Require approval (pause before executing) ----------------------

async def demo_require_approval() -> None:
    """Action executor with require_approval -- pauses for human review."""
    print("\n" + "=" * 60)
    print("DEMO: action_executor with require_approval policy")
    print("=" * 60)

    agent = Agent(
        agent_id="emailer",
        role="Email Sender",
        system_prompt="Send emails as instructed.",
        behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
        tools=[MockToolPlugin()],
        llm_provider=ToolCallingProvider(),
        action_policy="require_approval",
    )

    steps = [WorkflowStep(agent="emailer", step_type=StepType.SEQUENTIAL)]
    engine = WorkflowEngine(steps)
    result = await engine.execute(
        {"emailer": agent},
        {"task": "Send a welcome email to new-hire@company.com"},
    )

    print(f"Status: {result.status.value}")
    print(f"Awaiting approval: {result.state.get('awaiting_action_approval', False)}")

    # Inspect proposed actions (not yet executed)
    proposed = result.state.get("emailer_proposed_actions", [])
    print(f"\nProposed actions ({len(proposed)}):")
    for action in proposed:
        print(f"  Tool: {action['tool']}")
        print(f"  Args: {action['arguments']}")
        print("  (Waiting for human approval before execution)")


# -- Main -----------------------------------------------------------------------

async def main() -> None:
    await demo_auto_policy()
    await demo_require_approval()


if __name__ == "__main__":
    asyncio.run(main())
