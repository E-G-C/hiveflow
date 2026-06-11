# Quickstart: MCP Integration & Conversational Memory

**Feature**: 007-mcp-memory-integrations
**Date**: 2026-02-25

---

## Minimal Working Example

### 1. Configure an MCP server

Create `.hiveflow/mcp.json`:

```json
{
  "strategy": "fast",
  "servers": [
    {
      "name": "local_tools",
      "transport": "stdio",
      "command": "my-mcp-tool-server",
      "args": ["--verbose"]
    }
  ]
}
```

### 2. Reference MCP tools in a team config

```yaml
# team_config.yaml
team_name: research_team
description: Team with native and MCP tools

agents:
  - id: researcher
    role: Research assistant
    system_prompt: You are a research assistant with access to search and database tools.
    behavior_type: tool_user
    tools:
      - web_search
      - mcp:local_tools/file_read
      - mcp:local_tools/file_write

workflow:
  steps:
    - agent: researcher
      type: sequential
```

### 3. Run the workflow

```python
from hiveflow import HiveFlow

hf = HiveFlow()
session = await hf.run(
    team="research_team",
    task="Find and summarize the latest quarterly report",
)
```

The framework:
1. Loads `mcp.json`, sees `strategy: "fast"`
2. Spawns `my-mcp-tool-server --verbose` via stdio
3. Discovers `file_read` and `file_write` tools
4. Registers `mcp:local_tools/file_read` and `mcp:local_tools/file_write` in the tool registry
5. Builds the `researcher` agent with `[web_search, mcp:local_tools/file_read, mcp:local_tools/file_write]`
6. Runs the workflow — agent sees all three tools and can invoke any of them
7. On completion, terminates the spawned MCP server process

---

## HTTP Transport with Authentication

```json
{
  "strategy": "fast",
  "servers": [
    {
      "name": "jira",
      "transport": "http",
      "url": "http://mcp-jira-server:8080",
      "auth": { "type": "bearer", "env": "JIRA_MCP_TOKEN" }
    }
  ]
}
```

Set the token:
```bash
export JIRA_MCP_TOKEN="your-token-here"
```

Reference in team config:
```yaml
tools:
  - mcp:jira/search
  - mcp:jira/create_issue
```

---

## Lazy Connection

For servers that are expensive to start or only sometimes needed:

```json
{
  "strategy": "fast",
  "servers": [
    {
      "name": "heavy_analytics",
      "transport": "http",
      "url": "http://analytics-mcp:9090",
      "lazy": true
    }
  ]
}
```

The `heavy_analytics` server is only connected when an agent first references one of its tools. If no agent uses it during the workflow, it is never contacted.

---

## Per-Team Strategy Override

Override the global MCP strategy for a specific team:

```yaml
# team_config.yaml
team_name: simple_team
mcp_strategy: disabled

agents:
  - id: writer
    role: Content writer
    system_prompt: You write content.
    behavior_type: llm_only

workflow:
  steps:
    - agent: writer
      type: sequential
```

Even if `mcp.json` has `strategy: "fast"`, this team runs with MCP disabled.

---

## Checkpoint Cold-Resume

Workflows that pause at gates now persist enough data for cold-resume:

```python
# Start a workflow that pauses at a gate
session = await hf.run(team="approval_flow", task="Review the PR")
# session.status == PAUSED

# ---- process restarts ----

# Resume from checkpoint only (no in-memory session available)
hf = HiveFlow()  # fresh instance
session = await hf.resume(
    session_id="abc-123",
    responses={"gate_approval": True},
)
# Works! team_config and task are restored from checkpoint.
```

---

## Mixed Native + MCP Tools

Native tools and MCP tools coexist in the same agent:

```yaml
agents:
  - id: analyst
    role: Data analyst
    system_prompt: Analyze data using available tools.
    behavior_type: tool_user
    tools:
      - web_search                    # native tool
      - document_retriever            # native tool
      - mcp:company_db/query          # MCP tool
      - mcp:company_db/insert         # MCP tool
      - mcp:jira/search               # MCP tool from different server
```

The agent sees all five tools in a single unified list. It does not know or care which are native and which are MCP.

---

## Verifying MCP is Off

When no `mcp.json` exists and no `HIVEFLOW_MCP_CONFIG` env var is set, MCP is silently disabled. Existing workflows continue to work identically. You can verify:

```python
from hiveflow.plugins.mcp.config import MCPConfig

config = MCPConfig.from_file()
assert config.strategy == "disabled"
assert config.servers == []
```
