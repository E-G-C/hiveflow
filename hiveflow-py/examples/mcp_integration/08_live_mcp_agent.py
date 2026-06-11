#!/usr/bin/env python3
"""MCP Integration 08: Live MCP Agent with Azure OpenAI.

End-to-end demo: spawns a real MCP tool server, connects to it,
discovers tools, and runs an Azure gpt-4o agent that uses them.

What happens:
  1. Spawns tools_server.py as a stdio MCP server subprocess
  2. MCPManager connects and discovers 5 tools
  3. Builds a tool_user Agent backed by Azure OpenAI gpt-4o
  4. Agent receives a task, decides which tools to call, calls them,
     and produces a final answer using real LLM reasoning
  5. Prints the full tool call chain and final output

Requires:
  - Azure OpenAI endpoint with RBAC (az login) or API key
  - The tools_server.py file in the same directory

Usage:
    AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com \\
        uv run python examples/mcp_integration/08_live_mcp_agent.py

    # Or with a specific task:
    AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com \\
        uv run python examples/mcp_integration/08_live_mcp_agent.py \\
        --task "What is the capital of France and what is the weather there?"
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
from hiveflow.plugins.llm import LLMConfig
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
from hiveflow.plugins.mcp.config import MCPConfig, MCPServerDefinition
from hiveflow.plugins.mcp.manager import MCPManager
from hiveflow.plugins.tools import ToolRegistry

# Path to the MCP tool server script
TOOLS_SERVER = str(Path(__file__).parent / "tools_server.py")

AZURE_ENDPOINT = os.environ.get(
    "AZURE_OPENAI_ENDPOINT",
    "https://foundry-aisbx-we.cognitiveservices.azure.com",
)
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

DEFAULT_TASK = (
    "I need a brief travel briefing for Tokyo: "
    "what's the capital status, current weather, "
    "and give me a fun fact about Japan or Tokyo. "
    "Also, how many words are in your final answer?"
)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def build_mcp_config() -> MCPConfig:
    """Configure MCP to spawn our tools server via stdio."""
    return MCPConfig(
        strategy="fast",
        servers=[
            MCPServerDefinition(
                name="research_tools",
                transport="stdio",
                command=sys.executable,
                args=[TOOLS_SERVER],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(task: str) -> None:
    print("=" * 65)
    print("  HiveFlow -- Live MCP Agent with Azure OpenAI")
    print("=" * 65)
    print()
    print(f"  Endpoint:    {AZURE_ENDPOINT}")
    print(f"  Deployment:  {DEPLOYMENT}")
    print(f"  MCP server:  {Path(TOOLS_SERVER).name}")
    print(f"  Task:        {task[:70]}{'...' if len(task) > 70 else ''}")
    print()

    # -- 1. Create Azure LLM provider --
    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)

    # -- 2. Set up MCP Manager and discover tools --
    print("--- MCP Tool Discovery ---")
    config = build_mcp_config()
    registry = ToolRegistry(drop_in_dir=None)
    manager = MCPManager(config, registry)

    await manager.startup(task=task)
    mcp_tools = manager.get_tools()
    print(f"  Discovered {len(mcp_tools)} tools:")
    for tool in mcp_tools:
        print(f"    {tool.plugin_id:45s}  {tool.description[:45]}")
    print()

    # -- 3. Build agent with MCP tools --
    agent = Agent(
        agent_id="assistant",
        role="Research Assistant",
        system_prompt=(
            "You are a helpful research assistant with access to external tools. "
            "Use the available tools to gather information and answer the user's "
            "question thoroughly. Call multiple tools if needed, then synthesize "
            "the results into a clear, well-structured answer."
        ),
        behavior_type=AgentBehaviorType.TOOL_USER,
        tools=mcp_tools,
        model=f"azure:{DEPLOYMENT}",
        llm_provider=provider,
        llm_config=LLMConfig(model=DEPLOYMENT, max_tokens=1500),
        max_tool_iterations=8,
    )

    # -- 4. Build and run workflow --
    print("--- Running Workflow ---")
    steps = [
        WorkflowStep(agent="assistant", step_type=StepType.SEQUENTIAL),
    ]
    engine = WorkflowEngine(steps)

    # Event callback for live progress
    def on_event(event_type: str, agent_id: str, data: dict) -> None:
        if event_type == "step_start":
            print(f"  > Agent '{agent_id}' starting...")
        elif event_type == "step_complete":
            print(f"  * Agent '{agent_id}' complete")

    engine.on_event(on_event)

    result = await engine.execute(
        agents={"assistant": agent},
        initial_state={"task": task},
    )

    # -- 5. Display results --
    print()
    print(f"--- Results (status: {result.status.value}) ---")
    state = result.state
    output = state.get("assistant_output", "")
    usage = state.get("assistant_usage", {})
    tool_calls = state.get("assistant_tool_results", [])

    if tool_calls:
        print(f"\n  Tool calls made: {len(tool_calls)}")
        for i, tc in enumerate(tool_calls, 1):
            name = tc.get("tool", "unknown")
            inp = tc.get("input", {})
            out = tc.get("output", {})
            # Show tool name and result summary
            result_text = str(out.get("result", out) if isinstance(out, dict) else out)
            if len(result_text) > 80:
                result_text = result_text[:80] + "..."
            inp_text = str(inp)
            if len(inp_text) > 50:
                inp_text = inp_text[:50] + "..."
            print(f"    {i}. {name}({inp_text})")
            print(f"       -> {result_text}")
        print()

    if output:
        words = len(output.split())
        tokens = usage.get("total_tokens", 0) if usage else 0
        print(f"  Output ({words} words, {tokens} tokens):")
        print(f"  {'-' * 55}")
        # Indent the output
        for line in output.split("\n"):
            print(f"  {line}")
    else:
        print("  (no output)")

    # -- 6. Shutdown MCP --
    await manager.shutdown()
    print(f"\n{'=' * 65}")
    print("  Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live MCP + Azure OpenAI demo")
    parser.add_argument("--task", default=DEFAULT_TASK, help="Task for the agent")
    args = parser.parse_args()

    asyncio.run(run(task=args.task))
