#!/usr/bin/env python3
"""Example: Checkpoint resume -- pause a workflow at a gate, then resume it.

Demonstrates how to:
1. Execute a workflow that auto-checkpoints at a gated step
2. Inspect the saved checkpoint after the workflow pauses
3. Resume the workflow from the checkpoint with approval responses
4. Resume from a specific checkpoint_id to "rewind" a workflow
5. Handle checkpoint validation errors

This is an end-to-end example of the checkpoint/resume cycle. The
workflow runs through a drafter agent, auto-checkpoints at a review
gate, then resumes to execute the publisher agent.

By default uses a mock LLM provider (no API keys needed).
Set AZURE_OPENAI_ENDPOINT to use Azure OpenAI with RBAC auth:

    export AZURE_OPENAI_ENDPOINT=https://<resource>.cognitiveservices.azure.com
    uv run python examples/core_architecture/09_checkpoint_resume.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    FileCheckpointStorage,
    WorkflowStatus,
)
from hiveflow.core.checkpoint import CheckpointError
from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


class MockProvider(LLMProvider):
    """Returns a canned response based on agent role."""

    def __init__(self, response: str = "Done."):
        self._response = response

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
            content=self._response,
            model="mock",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


def _get_provider(fallback_response: str = "Done.") -> LLMProvider:
    """Return Azure provider if AZURE_OPENAI_ENDPOINT is set, else mock."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from hiveflow.plugins.llm import get_llm_registry
        registry = get_llm_registry()
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        provider, _ = registry.resolve_model(f"azure:{deployment}")
        return provider
    return MockProvider(fallback_response)


def _get_model() -> str | None:
    """Return the Azure deployment name if using Azure, else None."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    return None


def build_agents() -> dict[str, Agent]:
    """Create agents -- live Azure or mock depending on environment."""
    provider = _get_provider()
    model = _get_model()
    model_kwarg = {"model": f"azure:{model}"} if model else {}
    return {
        "drafter": Agent(
            agent_id="drafter",
            role="Content Drafter",
            system_prompt="You are a content drafter. Write a short 2-3 sentence draft about the given topic. Be concise.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            **model_kwarg,
        ),
        "publisher": Agent(
            agent_id="publisher",
            role="Publisher",
            system_prompt="You are a publisher. Finalize the approved content by adding a short closing line. Be concise.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            **model_kwarg,
        ),
    }


def build_steps() -> list[WorkflowStep]:
    """Define a drafter -> gate -> publisher workflow."""
    return [
        WorkflowStep(
            agent="drafter",
            step_type=StepType.SEQUENTIAL,
            next_step="review_gate",
        ),
        WorkflowStep(
            agent="review_gate",
            step_type=StepType.GATED,
            gate_id="review_gate",
            gate_description="Review the draft before publishing",
            next_step="publisher",
        ),
        WorkflowStep(
            agent="publisher",
            step_type=StepType.SEQUENTIAL,
        ),
    ]


async def main() -> None:
    """Full checkpoint/resume lifecycle."""
    live = bool(os.environ.get("AZURE_OPENAI_ENDPOINT"))
    mode = "Azure OpenAI (RBAC)" if live else "Mock provider"
    print(f"Checkpoint Resume Example  [{mode}]")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileCheckpointStorage(directory=tmpdir)
        agents = build_agents()
        steps = build_steps()

        # -- Phase 1: Execute until gate ---------------------------------
        print("\n--- Phase 1: Execute workflow (will pause at gate) ---")
        engine = WorkflowEngine(steps)
        result = await engine.execute(
            agents,
            {"task": "Write a blog post about AI safety"},
            checkpoint_storage=storage,
            session_id="blog-session",
        )

        print(f"Status: {result.status.value}")
        drafter_out = result.state.get("drafter_output", "")
        print(f"Drafter output: {drafter_out[:80]}{'...' if len(drafter_out) > 80 else ''}")
        print(f"Gate ID: {result.state.get('pending_gate_id')}")
        assert result.status == WorkflowStatus.PAUSED

        # -- Phase 2: Inspect checkpoint ---------------------------------
        print("\n--- Phase 2: Inspect saved checkpoint ---")
        checkpoints = await storage.list_checkpoints("blog-session")
        print(f"Checkpoints saved: {len(checkpoints)}")
        cp = checkpoints[0]
        print(f"  ID: {cp.checkpoint_id[:12]}...")
        print(f"  Step: {cp.step_index} ({cp.current_agent_id})")
        print(f"  Type: {cp.current_step_type}")

        # -- Phase 3: Resume with approval -------------------------------
        # In a real app, a human reviews the draft and provides approval.
        # Here we simulate approval by passing responses to resume().
        print("\n--- Phase 3: Resume with approval ---")
        checkpoint = await storage.load("blog-session")
        assert checkpoint is not None

        engine2 = WorkflowEngine(steps)
        result2 = await engine2.resume(
            agents,
            checkpoint,
            responses={"approved": True, "feedback": "Great draft, publish it!"},
            checkpoint_storage=storage,
            session_id="blog-session",
        )

        print(f"Status: {result2.status.value}")
        publisher_out = result2.state.get("publisher_output", "")
        print(f"Publisher output: {publisher_out[:80]}{'...' if len(publisher_out) > 80 else ''}")
        assert result2.status == WorkflowStatus.COMPLETED

        # -- Phase 4: Rewind to a specific checkpoint --------------------
        # If a workflow has multiple gates, each produces a checkpoint.
        # You can resume from any of them.
        print("\n--- Phase 4: Rewind to specific checkpoint ---")
        all_checkpoints = await storage.list_checkpoints("blog-session")
        print(f"Total checkpoints: {len(all_checkpoints)}")
        target_id = all_checkpoints[0].checkpoint_id
        rewound = await storage.load("blog-session", target_id)
        assert rewound is not None
        print(f"Rewound to checkpoint: {target_id[:12]}...")
        print(f"  Step: {rewound.step_index} ({rewound.current_agent_id})")

        # -- Phase 5: Error handling -------------------------------------
        print("\n--- Phase 5: Checkpoint validation errors ---")
        from hiveflow import WorkflowCheckpoint

        bad_checkpoint = WorkflowCheckpoint(
            session_id="blog-session",
            step_index=99,  # Out of range
            state={},
        )
        engine3 = WorkflowEngine(steps)
        try:
            await engine3.resume(agents, bad_checkpoint)
        except CheckpointError as e:
            print(f"Caught CheckpointError: {e}")

    print("\n" + "=" * 60)
    print("Done. The full cycle: execute -> pause -> checkpoint -> resume -> complete")


if __name__ == "__main__":
    asyncio.run(main())
