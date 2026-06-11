# MCP Integration Examples

Demonstrates HiveFlow's Model Context Protocol (MCP) integration -- connecting
agents to external tool servers and exposing workflows as MCP tools.

All examples 01-07 run with **mock providers** by default (no MCP servers or API
keys required). Example 08 is a **live demo** requiring Azure OpenAI.

## Examples

| # | File | Concepts |
|---|------|----------|
| 01 | `01_mcp_configuration.py` | MCPConfig, MCPServerDefinition, MCPAuthConfig, from_file(), strategies |
| 02 | `02_tool_bridge.py` | MCPToolBridge, plugin_id, llm_name, execute(), to_llm_tool_spec() |
| 03 | `03_manager_lifecycle.py` | MCPManager, startup/shutdown, eager/lazy connections, tool discovery |
| 04 | `04_mixed_tools.py` | Native + MCP tools in same agent, ToolRegistry, unified tool list |
| 05 | `05_deep_mode_selection.py` | Deep mode strategy, LLM-assisted tool filtering, fallback behavior |
| 06 | `06_mcp_gateway.py` | MCPGateway, expose workflows as MCP tools, FastMCP server |
| 07 | `07_checkpoint_cold_resume.py` | Checkpoint persistence, team_config/task, cold-resume after restart |
| -- | `tools_server.py` | FastMCP tool server (5 tools) -- used by example 08 |
| 08 | `08_live_mcp_agent.py` | **Live demo**: spawns MCP server, Azure gpt-4o agent uses real tools |

## Running

```bash
# Run any example
uv run python examples/mcp_integration/01_mcp_configuration.py

# Run all sequentially
for f in examples/mcp_integration/0*.py; do uv run python "$f"; echo; done
```

## Prerequisites

- HiveFlow installed (`uv add -e .`)
- Examples 01-07: no API keys or MCP servers required
- Example 08 (live): Azure OpenAI endpoint with RBAC (`az login`) or API key

```bash
# Run the live demo
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com \
    uv run python examples/mcp_integration/08_live_mcp_agent.py

# With a custom task
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com \
    uv run python examples/mcp_integration/08_live_mcp_agent.py \
    --task "Calculate 365*24 and check the weather in London"
```

## Key Concepts

- **Strategy**: `disabled` (off), `fast` (register all tools), `deep` (LLM selects relevant tools)
- **Transport**: `stdio` (local subprocess) or `http` (remote URL with optional auth)
- **Tool ID format**: `mcp:{server_name}/{tool_name}` (e.g. `mcp:github/search_repos`)
- **LLM name format**: `mcp_{server}__{tool}` (sanitized for function calling)
- **Gateway**: Reverse direction -- expose HiveFlow workflows as MCP tools for external clients
