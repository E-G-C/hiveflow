"""Source Mode — controlling data retrieval pipelines.

Demonstrates how to use the source_mode field on TeamConfiguration to
control which retrieval and ingestion plugins are active for a workflow run.

Usage:
    uv run python examples/data_processing/source_mode_routing.py
"""

from hiveflow import (
    HiveFlowConfig,
    SourceMode,
    SourceModeRouter,
    SourceOptions,
    TeamConfiguration,
)


def main() -> None:
    # ── 1. Source Mode enum ──────────────────────────────────────────
    print("=== Source Mode Values ===")
    for mode in SourceMode:
        print(f"  {mode.value:10s}  ({mode.name})")

    # ── 2. Router — no mode (pass-through) ──────────────────────────
    print("\n=== No source mode (default) ===")
    router = SourceModeRouter()
    tools = ["web_search", "document_retriever", "delegate_task"]
    print(f"  Input tools:    {tools}")
    print(f"  Filtered tools: {router.filter_tools(tools)}")
    print(f"  (all pass through when no mode is set)")

    # ── 3. Router — web mode ────────────────────────────────────────
    print("\n=== Web mode ===")
    router = SourceModeRouter(source_mode="web")
    tools = ["web_search", "document_retriever", "scraper_bs4", "delegate_task"]
    filtered = router.filter_tools(tools)
    print(f"  Input tools:    {tools}")
    print(f"  Filtered tools: {filtered}")
    print(f"  Allowed categories: {router.get_allowed_categories()}")

    # ── 4. Router — local mode ──────────────────────────────────────
    print("\n=== Local mode ===")
    router = SourceModeRouter(source_mode="local")
    tools = ["web_search", "document_retriever", "vector_store_search", "delegate_task"]
    filtered = router.filter_tools(tools)
    print(f"  Input tools:    {tools}")
    print(f"  Filtered tools: {filtered}")

    # ── 5. Router — hybrid mode (web + local) ───────────────────────
    print("\n=== Hybrid mode ===")
    router = SourceModeRouter(source_mode="hybrid")
    tools = ["web_search", "document_retriever", "scraper_bs4", "vector_store_search"]
    filtered = router.filter_tools(tools)
    print(f"  Input tools:    {tools}")
    print(f"  Filtered tools: {filtered}")
    print(f"  (hybrid passes both web and local tools)")

    # ── 6. Router — custom mode ─────────────────────────────────────
    print("\n=== Custom mode ===")
    router = SourceModeRouter(
        source_mode="custom",
        source_options={"custom_plugins": ["my_special_tool", "internal_db"]},
    )
    tools = ["my_special_tool", "web_search", "internal_db", "document_retriever"]
    filtered = router.filter_tools(tools)
    print(f"  Input tools:    {tools}")
    print(f"  Filtered tools: {filtered}")

    # ── 7. TeamConfiguration with source_mode ───────────────────────
    print("\n=== TeamConfiguration with source_mode ===")
    config = TeamConfiguration(
        team_name="research_report",
        description="Research team with hybrid data sources",
        source_mode="hybrid",
        source_options={
            "web": {"retrievers": ["tavily", "duckduckgo"], "max_results_per_query": 10},
            "local": {"doc_path": "./docs/healthcare", "formats": ["pdf", "docx", "md"]},
        },
        agents=[{
            "id": "researcher",
            "role": "Research analyst",
            "system_prompt": "You are a research analyst. Use available tools to gather data.",
            "behavior_type": "tool_user",
            "tools": ["web_search", "document_retriever", "scraper_bs4"],
        }],
        workflow={"steps": [{"agent": "researcher", "type": "sequential"}]},
    )
    print(f"  Team:           {config.team_name}")
    print(f"  Source mode:    {config.source_mode}")
    print(f"  Source options: {config.source_options}")

    # The router can be created from the config values
    router = SourceModeRouter(
        source_mode=config.source_mode,
        source_options=config.source_options,
    )
    agent_tools = config.agents[0].tools
    filtered = router.filter_tools(agent_tools)
    print(f"  Agent tools:    {agent_tools}")
    print(f"  After routing:  {filtered}")

    # ── 8. Config defaults ──────────────────────────────────────────
    print("\n=== HiveFlowConfig defaults ===")
    cfg = HiveFlowConfig()
    print(f"  SOURCE_MODE:    {cfg.SOURCE_MODE}")
    print(f"  DOC_PATH:       {cfg.DOC_PATH}")

    print("\nDone!")


if __name__ == "__main__":
    main()
