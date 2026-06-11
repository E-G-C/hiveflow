# API Contracts: Dynamic Agent Collaboration

**Feature**: 010-dynamic-agent-collaboration
**Date**: 2026-03-04

These contracts define the tool plugin interfaces (LLM-facing tool specs) and the internal Python APIs for the collaboration system.

## Tool Plugin Contracts (LLM-facing)

### delegate_task

```json
{
  "type": "function",
  "function": {
    "name": "delegate_task",
    "description": "Delegate a sub-task to another agent or a sub-team. The task will be executed and the result returned to you.",
    "parameters": {
      "type": "object",
      "properties": {
        "task": {
          "type": "string",
          "description": "Clear description of the sub-task to delegate"
        },
        "delegate_to": {
          "type": "string",
          "description": "Agent ID to delegate to, or 'auto' to let the system choose the best agent"
        },
        "context": {
          "type": "object",
          "description": "Additional context to pass to the delegate (merged into its state)"
        },
        "expected_output": {
          "type": "string",
          "enum": ["text", "structured_data", "decision"],
          "description": "What kind of output you expect back"
        }
      },
      "required": ["task"]
    }
  }
}
```

**Returns**: `{"status": "completed"|"failed"|"timeout", "result": "...", "agent_id": "...", "tokens_used": N}`

---

### spawn_agent

```json
{
  "type": "function",
  "function": {
    "name": "spawn_agent",
    "description": "Create a new specialist agent from an archetype or custom definition. Returns the agent's ID for use with delegate_task.",
    "parameters": {
      "type": "object",
      "properties": {
        "archetype": {
          "type": "string",
          "description": "Name of an archetype from the library (e.g., 'researcher', 'writer', 'reviewer'). Use list_archetypes to see available options."
        },
        "custom_definition": {
          "type": "object",
          "description": "Inline agent definition if no archetype fits.",
          "properties": {
            "role": { "type": "string", "description": "Agent role name" },
            "system_prompt": { "type": "string", "description": "System prompt for the agent" },
            "behavior_type": { "type": "string", "enum": ["llm_only", "tool_user"], "default": "llm_only" },
            "tools": { "type": "array", "items": { "type": "string" }, "description": "Tool IDs to grant access to (must be subset of parent + archetype tools)" }
          },
          "required": ["role", "system_prompt"]
        },
        "agent_id": {
          "type": "string",
          "description": "Optional custom ID for the spawned agent. Auto-generated if omitted."
        }
      }
    }
  }
}
```

**Returns**: `{"status": "spawned", "agent_id": "...", "role": "...", "available_tools": [...]}`

---

### send_message

```json
{
  "type": "function",
  "function": {
    "name": "send_message",
    "description": "Send a message to another agent. The message will be available in their next execution context.",
    "parameters": {
      "type": "object",
      "properties": {
        "to": {
          "type": "string",
          "description": "Target agent ID, or 'broadcast' to send to all agents"
        },
        "subject": {
          "type": "string",
          "description": "Brief subject line for the message"
        },
        "body": {
          "type": "string",
          "description": "The message content"
        },
        "requires_response": {
          "type": "boolean",
          "description": "Whether you need a response from the target agent",
          "default": false
        }
      },
      "required": ["to", "body"]
    }
  }
}
```

**Returns**: `{"status": "sent", "message_id": "...", "to": "..."}`

---

### read_messages

```json
{
  "type": "function",
  "function": {
    "name": "read_messages",
    "description": "Read messages sent to you by other agents.",
    "parameters": {
      "type": "object",
      "properties": {
        "unread_only": {
          "type": "boolean",
          "description": "If true, only return unread messages",
          "default": true
        }
      }
    }
  }
}
```

**Returns**: `{"messages": [{"from": "...", "subject": "...", "body": "...", "requires_response": bool, "timestamp": "..."}], "count": N}`

---

## Internal Python API Contracts

### CollaborationRuntime

```python
class CollaborationRuntime:
    """Manages the runtime agent pool, delegation tracking, and budget enforcement."""

    def __init__(
        self,
        config: CollaborationConfig,
        initial_agents: dict[str, Agent],
        archetype_library: ArchetypeLibrary,
        tool_registry: ToolRegistry,
        llm_provider: LLMProvider,
        llm_config: LLMConfig,
        stream_channel: StreamChannel | None = None,
    ) -> None: ...

    # Agent Pool
    def get_agent(self, agent_id: str) -> Agent | None: ...
    def list_agents(self) -> list[str]: ...
    def register_agent(self, agent: Agent) -> None: ...

    # Spawning
    def spawn_from_archetype(
        self, archetype_name: str, agent_id: str | None = None,
        parent_tools: list[str] | None = None,
    ) -> Agent: ...
    def spawn_from_definition(
        self, definition: dict[str, Any], agent_id: str | None = None,
        parent_tools: list[str] | None = None,
    ) -> Agent: ...
    @property
    def can_spawn(self) -> bool: ...

    # Delegation
    async def delegate(
        self, task: str, delegate_to: str, delegated_by: str,
        context: dict[str, Any] | None = None,
        parent_state: dict[str, Any] | None = None,
    ) -> DelegationRecord: ...
    def check_depth(self, current_depth: int) -> bool: ...

    # Auto-selection
    def select_best_agent(self, task_description: str) -> str | None: ...

    # Budget
    def get_remaining_budget(self, parent_agent_id: str) -> int | None: ...
    def record_usage(self, agent_id: str, tokens: int) -> None: ...
```

### CollaborationConfig (Pydantic Model)

```python
class CollaborationConfig(BaseModel):
    enabled: bool = False
    max_delegation_depth: int = Field(default=3, ge=1)
    max_spawned_agents: int = Field(default=10, ge=1)
    allow_recursive_orchestrators: bool = False
    delegation_timeout_seconds: int = Field(default=300, ge=1)
    budget_policy: Literal["inherit_parent", "fixed", "unlimited"] = "inherit_parent"
    fixed_budget_tokens: int | None = None

    @model_validator(mode="after")
    def validate_fixed_budget(self) -> "CollaborationConfig": ...
```

### Tool Plugin Base Signatures

```python
class DelegateTaskTool(ToolPlugin):
    plugin_id: str = "delegate_task"
    def __init__(self, runtime: CollaborationRuntime, caller_agent_id: str) -> None: ...
    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]: ...

class SpawnAgentTool(ToolPlugin):
    plugin_id: str = "spawn_agent"
    def __init__(self, runtime: CollaborationRuntime, caller_agent_id: str) -> None: ...
    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]: ...

class SendMessageTool(ToolPlugin):
    plugin_id: str = "send_message"
    def __init__(self, caller_agent_id: str) -> None: ...
    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]: ...

class ReadMessagesTool(ToolPlugin):
    plugin_id: str = "read_messages"
    def __init__(self, caller_agent_id: str) -> None: ...
    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]: ...
```

### WorkflowEngine Integration Points

```python
# In WorkflowEngine.__init__ or _build_agents():
# When collaboration.enabled is True:
#   1. Create CollaborationRuntime from merged config
#   2. Register pre-configured agents in runtime.agent_pool
#   3. For each orchestrator agent:
#      - Create DelegateTaskTool(runtime, agent.agent_id)
#      - Create SpawnAgentTool(runtime, agent.agent_id)
#      - Create SendMessageTool(agent.agent_id)
#      - Create ReadMessagesTool(agent.agent_id)
#      - Append to agent.tools
#   4. Store runtime in state["_collaboration_runtime"]
```
