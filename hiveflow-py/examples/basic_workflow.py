"""Example: Basic multi-agent workflow with HiveFlow.

Demonstrates how to:
1. Create agents with different behavior types
2. Build a workflow graph with summary propagation
3. Execute the workflow and inspect results
4. Use context budgets to control what each agent sees
"""

import asyncio

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStep,
)


async def main() -> None:
    """Run a basic researcher -> writer workflow with summary propagation."""

    # Create agents
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt=(
            "You are a research analyst. Given a topic, search for "
            "relevant information and provide a comprehensive summary."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model="perplexity:sonar-pro",
    )

    writer = Agent(
        agent_id="writer",
        role="Report Writer",
        system_prompt=(
            "You are a professional writer. Based on the research data "
            "provided, write a clear, well-structured report."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model="perplexity:sonar-pro",
        # Limit context to 4000 words so the writer isn't overwhelmed
        context_budget=4000,
    )

    # Define workflow steps
    steps = [
        WorkflowStep(
            agent="researcher",
            step_type="sequential",
            next_step="writer",
        ),
        WorkflowStep(
            agent="writer",
            step_type="sequential",
        ),
    ]

    # Create engine with summary propagation and code-level assembly.
    # The summarizer generates compact summaries (~200 tokens) after each
    # agent step so downstream agents receive condensed context instead
    # of the full output.  assembly_agents stitches the specified agents'
    # full outputs into a single final_output key.
    #
    # NOTE: SummaryGenerator needs an LLM provider. In a real app you'd
    # pass the same provider used for agents. Here we omit it to keep the
    # example self-contained (the summarizer just won't be used without one).
    engine = WorkflowEngine(
        steps,
        assembly_agents=["writer"],  # assemble writer output into final_output
    )

    # Register event callback for observability
    def on_event(event_type: str, agent_id: str, _data: dict) -> None:  # type: ignore[type-arg]
        print(f"[{event_type}] Agent: {agent_id}")

    engine.on_event(on_event)

    # Run workflow
    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Explain the benefits of renewable energy"},
    )

    print(f"\nWorkflow status: {result.status}")
    print(f"Steps executed: {len(result.step_results)}")
    for step in result.step_results:
        print(f"  - {step.agent_id}: {step.status}")

    # The final assembled document is in final_output
    if "final_output" in result.state:
        print(f"\nAssembled output length: {len(result.state['final_output'].split())} words")


if __name__ == "__main__":
    asyncio.run(main())
