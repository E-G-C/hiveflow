#!/usr/bin/env python3
"""Example: State schema enforcement -- control agent state writes.

Demonstrates how to:
1. Define a StateSchema with agent I/O mappings
2. Use 'warn' mode (allow all writes, log warnings for undeclared keys)
3. Use 'strict' mode (filter output to only declared write keys)
4. Use 'off' mode (no enforcement)

State schemas prevent agents from accidentally polluting shared workflow state.
This is especially useful in multi-agent workflows where state discipline matters.
"""

import asyncio
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
from hiveflow.core.schema import AgentIOMapping, StateSchema
from hiveflow.core.workflow import StepType
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


class MockProvider(LLMProvider):
    """Provider that returns a fixed response."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        return LLMResponse(
            content="Generated output text",
            model="mock",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


async def run_with_schema(mode: str) -> dict:
    """Run a workflow with the given enforcement mode and return state."""
    agent = Agent(
        agent_id="writer",
        role="Writer",
        system_prompt="Write content.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=MockProvider(),
    )

    # Declare that the writer agent is allowed to write 'writer_output'
    # but NOT 'writer_usage' (which the engine adds automatically)
    schema = StateSchema(
        enforcement_mode=mode,
        agent_io={"writer": AgentIOMapping(
            reads=["task"],
            writes=["writer_output"],
        )},
    )

    steps = [WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL)]
    engine = WorkflowEngine(steps, state_schema=schema)
    result = await engine.execute({"writer": agent}, {"task": "Write something"})

    return result.state


async def main() -> None:
    """Compare state schema enforcement modes."""
    print("State Schema Enforcement Example")
    print("=" * 60)

    # -- warn mode (default): allows everything, logs warnings ------------------
    print("\n1. mode='warn' -- allows all writes, warns on undeclared")
    state = await run_with_schema("warn")
    print(f"   State keys: {sorted(state.keys())}")
    print(f"   writer_output present: {'writer_output' in state}")
    print(f"   writer_usage present: {'writer_usage' in state}")
    print("   (writer_usage is undeclared but allowed with warning)")

    # -- strict mode: filters undeclared writes ---------------------------------
    print("\n2. mode='strict' -- filters out undeclared writes")
    state = await run_with_schema("strict")
    print(f"   State keys: {sorted(state.keys())}")
    print(f"   writer_output present: {'writer_output' in state}")
    print(f"   writer_usage present: {'writer_usage' in state}")
    print("   (writer_usage is filtered out because it's undeclared)")

    # -- off mode: no enforcement -----------------------------------------------
    print("\n3. mode='off' -- no enforcement at all")
    state = await run_with_schema("off")
    print(f"   State keys: {sorted(state.keys())}")
    print(f"   writer_output present: {'writer_output' in state}")
    print(f"   writer_usage present: {'writer_usage' in state}")
    print("   (everything passes through)")

    # -- Schema definition (for JSON configs) -----------------------------------
    print("\n4. Schema in JSON config format:")
    schema_json = {
        "state_schema": {
            "required_keys": ["task"],
            "enforcement_mode": "strict",
            "agent_io": {
                "researcher": {"reads": ["task"], "writes": ["findings"]},
                "writer": {"reads": ["task", "findings"], "writes": ["report"]},
            },
        },
    }
    print(f"   {schema_json}")


if __name__ == "__main__":
    asyncio.run(main())
