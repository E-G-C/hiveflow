"""Example: Load Workflow Instructions from a File via Python API.

Demonstrates how to:
1. Use instructions_file on HiveFlow.run() to load complex instructions
2. See mutual exclusivity with non-empty task
3. Run a live workflow with file-based instructions

Uses live Azure OpenAI via RBAC for the workflow execution.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    uv sync --extra llm-azure

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/config_operations/06_instructions_file.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

from hiveflow.core.documents import DocumentPipeline


async def main() -> None:
    # -- 1. Basic instructions file loading ------------------------------------
    print("--- 1. Load instructions from file ---")
    instructions_dir = Path(tempfile.mkdtemp(prefix="hiveflow_instructions_"))
    instructions_file = instructions_dir / "analysis-instructions.md"
    instructions_file.write_text(
        "# Analysis Instructions\n\n"
        "Analyze the following topic with these guidelines:\n"
        "1. Identify key trends and patterns\n"
        "2. Compare with historical data\n"
        "3. Provide actionable recommendations\n"
        "4. Write in a professional, analytical tone\n"
        "5. Target audience: C-level executives\n",
        encoding="utf-8",
    )

    pipeline = DocumentPipeline(working_dir=instructions_dir)
    content = await pipeline.load_instructions_file(str(instructions_file))
    print(f"  Loaded {len(content)} chars from {instructions_file.name}")
    print(f"  First line: {content.split(chr(10))[0]}")

    # -- 2. Mutual exclusivity -------------------------------------------------
    print("\n--- 2. Mutual exclusivity check ---")
    from hiveflow.core.hiveflow import HiveFlow

    hf = HiveFlow()
    try:
        await hf.run(
            team="nonexistent",
            task="Non-empty task",
            instructions_file=str(instructions_file),
        )
    except ValueError as e:
        print(f"  Caught ValueError: {e}")
    except Exception:
        pass  # Other errors (team not found) are expected

    # -- 3. Live workflow with instructions_file -------------------------------
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        print("\n--- 3. Skipped (set AZURE_OPENAI_ENDPOINT for live demo) ---")
        return

    print("\n--- 3. Live workflow with instructions from file ---")
    from hiveflow import Agent, AgentBehaviorType, WorkflowEngine, WorkflowStep
    from hiveflow.plugins.llm import LLMConfig, get_llm_registry

    registry = get_llm_registry()
    if "azure" not in registry.list_ids():
        print("  Azure provider not available. Install with: uv sync --extra llm-azure")
        return

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    provider, model = registry.resolve_model(f"azure:{deployment}")

    analyst = Agent(
        agent_id="analyst",
        role="Business Analyst",
        system_prompt=content,  # Use instructions from file as system prompt
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=300),
    )

    steps = [WorkflowStep(agent="analyst", step_type="sequential")]
    engine = WorkflowEngine(steps)

    result = await engine.execute(
        agents={"analyst": analyst},
        initial_state={"task": "The impact of generative AI on enterprise software"},
    )

    output = result.state.get("analyst_output", "")
    if result.status.value == "failed":
        print(f"  Status: {result.status} (expected if behind VNet)")
    else:
        print(f"  Status: {result.status}")
        print(f"  Output ({len(output.split())} words):")
        print(f"  {output[:300]}...")


if __name__ == "__main__":
    asyncio.run(main())
