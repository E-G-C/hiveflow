[< Back to Index](README.md)

---

## Team Configuration Schema

A strict JSON schema governs all team definitions, whether hand-authored
or LLM-generated. Example structure:

```json
{
  "team_name": "research_report",
  "version": "1.0",
  "description": "Multi-agent team for producing research reports",
  "agents": [
    {
      "id": "editor",
      "role": "Research Editor",
      "system_prompt": "You are an expert research editor...",
      "behavior_type": "orchestrator",
      "tools": ["planner"],
      "model": "gpt-4o",
      "max_tokens": 8192,
      "output_type": "structured_data"
    },
    {
      "id": "researcher",
      "role": "Deep Researcher",
      "system_prompt": "You are a thorough research analyst...",
      "behavior_type": "tool_user",
      "tools": ["web_search", "scraper"],
      "model": "gpt-4o",
      "output_type": "text"
    },
    {
      "id": "reviewer",
      "role": "Quality Reviewer",
      "system_prompt": "You are an expert reviewer...",
      "behavior_type": "llm_only",
      "tools": [],
      "model": "gpt-4o",
      "output_type": "structured_data"
    },
    {
      "id": "deployer",
      "role": "Deployment Agent",
      "system_prompt": "You execute deployment operations...",
      "behavior_type": "action_executor",
      "tools": ["ci_cd", "cloud_deploy", "notifier"],
      "model": "gpt-4o-mini",
      "output_type": "side_effect",
      "action_policy": "require_approval"
    }
  ],
  "workflow": {
    "steps": [
      { "agent": "editor", "type": "sequential", "next": "researcher" },
      { "agent": "researcher", "type": "parallel_fan_out", "next": "reviewer" },
      {
        "agent": "reviewer",
        "type": "conditional",
        "next_on_accept": "writer",
        "next_on_reject": "reviser"
      },
      { "agent": "reviser", "type": "sequential", "next": "reviewer" },
      { "agent": "writer", "type": "sequential", "next": "deployer" },
      {
        "agent": "deployer",
        "type": "gated",
        "gate": "human_approval",
        "next": null
      }
    ]
  },
  "state_schema": {
    "required_keys": ["task", "research_data", "draft", "review"],
    "agent_io": {
      "editor": { "reads": ["task"], "writes": ["sections"] },
      "researcher": { "reads": ["sections"], "writes": ["research_data"] },
      "deployer": { "reads": ["final_output"], "writes": ["deployment_status"] }
    }
  }
}
```

All LLM-generated configs **must be validated** against this schema before
execution to prevent runtime failures from inconsistent output. Validation
checks include: structural conformance, dangling references (agent IDs in
workflow steps that don't exist in the agent roster), and tool availability
(tools referenced by agents that aren't registered in the plugin registry).

---

## Agent Behavior Types

Not all agents are simple prompt-in/text-out. The framework supports distinct
execution behaviors:

| Behavior Type     | Description                                                                     | Example use                        |
| ----------------- | ------------------------------------------------------------------------------- | ---------------------------------- |
| `llm_only`        | Pure prompt → LLM → response                                                   | Any text-generation step           |
| `tool_user`       | Has access to external tools (search, scrape, code exec, APIs)                  | Any data-gathering or analysis step|
| `orchestrator`    | Can spawn and manage sub-workflows                                              | Any decomposition / planning step  |
| `human_gate`      | Pauses for human input/approval                                                 | Any approval checkpoint            |
| `action_executor` | **Performs real-world side effects** (API calls, deployments, file ops, notifications) | Any step with side effects   |

> **`self_configure` (Deferred):** A behavior type where the agent uses the LLM
> to select its own persona before executing. This is **deferred to a future
> release** because it is under-specified and its use case can be approximated
> by composing an `orchestrator` (that selects an archetype) with an `llm_only`
> agent (that executes with the selected persona). A formal definition will be
> added when the archetype library matures enough to support dynamic archetype
> selection at runtime.

### The `action_executor` Behavior Type (New in v2)

The original system only produced text. HiveFlow v2 treats **real-world actions
as first-class outputs**. An `action_executor` agent:

1. Receives a task and context from the workflow state
2. Uses the LLM to determine **which actions to take** (tool selection)
3. Executes the actions via its tool plugins
4. Reports the **results and side effects** back to the workflow state

**Action safety policies:**

| Policy              | Description                                                      |
| ------------------- | ---------------------------------------------------------------- |
| `auto`              | Execute immediately (for low-risk, reversible actions)           |
| `require_approval`  | Pause for human approval before executing                        |
| `dry_run`           | Show what would be executed without performing the action        |
| `confirm_on_error`  | Execute automatically but escalate to human on failure           |

These policies are configured per-agent in the team config:

```json
{
  "id": "deployer",
  "behavior_type": "action_executor",
  "action_policy": "require_approval",
  "rollback_on_failure": true
}
```

#### Implementation Phases

**Phase 1 (Core):**
- Add `ACTION_EXECUTOR` to the `AgentBehaviorType` enum
- Add `action_policy` field to `AgentDefinition` schema
- Implement the execution path in `Agent.execute()` (similar to `tool_user`
  but with a pre-execution policy check)
- Add `ActionRecord` entries to the workflow state (`actions_taken` key)

**Phase 2 (Safety & Recovery):**
- Structured audit trail logging per action
- Rollback stack (`rollback_on_failure`, `max_retry_count`)
- `dry_run` policy implementation (report planned actions without executing)
- `confirm_on_error` policy (auto-execute, escalate on failure)

---

## Agent Output Types

The `output_type` field on `AgentDefinition` declares what kind of result an
agent produces. This influences how the workflow engine handles the output.

| Value             | Meaning                                              | Engine handling                              |
| ----------------- | ---------------------------------------------------- | -------------------------------------------- |
| `text`            | Free-form prose or markdown                          | Merged into state; eligible for assembly     |
| `structured_data` | JSON-parseable structured output                     | Merged into state; validated as JSON         |
| `side_effect`     | Real-world action performed (no content output)      | Logged to audit trail; not assembled         |
| `composite`       | Both content and side effects                        | Content merged; side effects logged          |

The field is **optional**. When omitted, the framework infers the output type
from the agent's behavior type:

| Behavior Type    | Default Output Type |
| ---------------- | ------------------- |
| `llm_only`       | `text`              |
| `tool_user`      | `text`              |
| `orchestrator`   | `structured_data`   |
| `human_gate`     | `text`              |
| `action_executor`| `side_effect`       |

---

## Workflow Step Types

The workflow graph supports the following step types:

| Step Type          | Description                                              | Phase   |
| ------------------ | -------------------------------------------------------- | ------- |
| `sequential`       | Agent runs, then proceeds to `next`                      | Done    |
| `parallel_fan_out` | Agent runs once per parallel item from the previous step | Done    |
| `conditional`      | Branches to `next_on_accept` or `next_on_reject`         | Done    |
| `human_gate`       | Agent runs; workflow pauses if awaiting human input       | Done    |
| `gated`            | Workflow pauses **before** the agent runs, pending a gate | Phase 1 |
| `sub_workflow`     | Executes another team configuration as a nested workflow  | Phase 2 |

### The `gated` Step Type

The `gated` step type decouples the gate from the agent's behavior. Unlike
`human_gate` (which is a behavior type on the agent itself), `gated` is a
**workflow-level control** that pauses execution before a specific agent runs.

The gate type is specified via a `gate` field on the step definition:

```json
{
  "agent": "deployer",
  "type": "gated",
  "gate": "human_approval",
  "next": null
}
```

| Gate Type          | Description                                             | Phase   |
| ------------------ | ------------------------------------------------------- | ------- |
| `human_approval`   | Pauses for human approval before the agent executes     | Phase 1 |
| `automated_check`  | Runs a validation function; proceeds if it passes       | Future  |
| `webhook`          | Waits for an external webhook callback                  | Future  |

Phase 1 implements `human_approval` only (functionally equivalent to the
current `human_gate` behavior type but with cleaner separation of concerns).

The `gate` field is added to `WorkflowStepDefinition` and is required when
`type` is `gated`.

When combined with **workflow checkpointing** (see
[Workflows](02-workflows.md#workflow-checkpointing-inspired-by-microsoft-agent-framework)),
gated steps automatically checkpoint before pausing, enabling asynchronous
approval: the workflow process can stop, and resume later when the approval
arrives.

### The `sub_workflow` Step Type (Phase 2)

A step that executes another `TeamConfiguration` as a nested workflow. See
[Workflows — Sub-Workflows](02-workflows.md#sub-workflows-composition) for
details.

```json
{
  "agent": "research_team",
  "type": "sub_workflow",
  "team": "deep_research",
  "input_mapping": { "task": "research_question" },
  "output_mapping": { "research_data": "findings" },
  "next": "reviewer"
}
```

---

## State Schema Runtime Enforcement

The `state_schema.agent_io` mappings declare what state keys each agent reads
and writes. At runtime, the workflow engine can optionally enforce these
boundaries.

### Enforcement Mode

Enforcement is **warning-only by default** (Option A). When enabled, the
engine logs a warning if an agent writes a key it did not declare in its
`writes` list. This aids debugging without breaking existing workflows.

| Mode          | Behavior                                                        | Default |
| ------------- | --------------------------------------------------------------- | ------- |
| `warn`        | Log warnings for undeclared writes; pass full state to agents   | Yes     |
| `strict`      | Filter state to declared `reads`; reject undeclared `writes`    | No      |
| `off`         | No enforcement; full state passed, no checks                    | No      |

The mode is configured at the workflow engine level:

```python
engine = WorkflowEngine(
    workflow_steps=steps,
    state_enforcement="warn",  # "warn" | "strict" | "off"
)
```

When `state_schema` is not defined in the team config, enforcement is
automatically `off` regardless of the setting.

**Strict mode** (future) would:
- Filter the state before passing to the agent (only declared `reads` keys)
- Validate the agent's output (only accept declared `writes` keys)
- Reject undeclared writes with an error

This is particularly valuable for `action_executor` agents where controlling
what state an agent can see and modify is a safety concern.

---

## Action-Oriented Agents

The generalized framework extends beyond text generation to support agents that
**take real-world actions** as first-class outputs.

### Action Categories

| Category            | Examples                                                     | Risk Level |
| ------------------- | ------------------------------------------------------------ | ---------- |
| **Read-only**       | Query databases, read files, fetch metrics                   | Low        |
| **Create**          | Create files, open tickets, send messages                    | Medium     |
| **Modify**          | Update records, edit files, change configurations            | High       |
| **Deploy/Execute**  | Deploy services, restart processes, run migrations           | Critical   |
| **Destroy**         | Delete resources, revoke access, terminate services          | Critical   |

### Action Audit Trail

Every action executed by an agent is logged in a structured audit trail:

```json
{
  "action_id": "act_20260212_001",
  "agent_id": "deployer",
  "workflow_run_id": "run_abc123",
  "action": "deploy_service",
  "tool_id": "cloud_deploy",
  "input": { "service": "api-v2", "environment": "staging" },
  "output": { "status": "success", "deploy_id": "d-789" },
  "policy": "require_approval",
  "approved_by": "user@company.com",
  "timestamp": "2026-02-12T14:30:00Z",
  "reversible": true,
  "rollback_action": "rollback_deploy"
}
```

### Rollback Support

For reversible actions, agents can declare a rollback action. If a downstream
review step determines the action was incorrect, the framework can automatically
or manually trigger rollback:

```json
{
  "id": "deployer",
  "behavior_type": "action_executor",
  "rollback_on_failure": true,
  "max_retry_count": 2
}
```

---

## Archetypes (Reusable Agent Definitions)

An archetype is a reusable, standalone `AgentDefinition` that exists outside
any specific team. Archetypes are the **building blocks** (ingredients) that
compose into teams (recipes).

Archetypes are **configuration, not code**. They are stored as JSON files and
loaded by an `ArchetypeLibrary`, following the same pattern as team
configurations.

### Archetype Format

An archetype file is a standard `AgentDefinition` JSON with optional metadata:

```json
{
  "id": "researcher",
  "role": "Deep Researcher",
  "system_prompt": "You are a thorough research agent. Search for information, evaluate source quality, and synthesize findings.",
  "behavior_type": "tool_user",
  "tools": ["web_search"],
  "model_requirements": {
    "strengths": ["analysis", "reasoning"],
    "supports_tool_calling": true
  },
  "tags": ["research", "data_collection"],
  "description": "Searches for information, evaluates sources, synthesizes findings"
}
```

### Built-in Archetypes

The framework ships a set of built-in archetypes in the default templates
directory:

| Archetype          | Role               | Behavior Type  | Default Tools   | Purpose                                          |
| ------------------ | ------------------ | -------------- | --------------- | ------------------------------------------------ |
| `researcher`       | Deep Researcher    | `tool_user`    | `web_search`    | Search, evaluate sources, synthesize findings    |
| `planner`          | Task Planner       | `orchestrator` | —               | Decompose task into parallel sub-tasks           |
| `writer`           | Content Writer     | `llm_only`     | —               | Transform findings into documents                |
| `reviewer`         | Quality Reviewer   | `llm_only`     | —               | Evaluate accuracy, completeness, clarity         |
| `editor`           | Task Editor        | `orchestrator` | —               | Break down tasks, coordinate agent workflows     |
| `human_reviewer`   | Human Review Gate  | `human_gate`   | —               | Pause for human approval                         |

The archetype library is extensible. New archetypes can be added as JSON files
to any directory scanned by `ArchetypeLibrary`, or generated by an LLM and
saved for reuse.

### `ArchetypeLibrary`

```python
class ArchetypeLibrary:
    """Loads and provides access to reusable agent definitions."""

    def list_archetypes(self) -> list[str]
    def get(self, name: str) -> AgentDefinition | None
    def register(self, name: str, archetype: AgentDefinition) -> None

    @classmethod
    def default(cls) -> ArchetypeLibrary
        # Loads from <package>/templates/archetypes/

    @classmethod
    def from_directory(cls, path: Path) -> ArchetypeLibrary
```

### Archetypes in Team Composition

Archetypes are used **at team creation time**. When a team is composed (whether
by `TeamGenerator`, by the LLM, or by hand), archetypes are copied **inline**
into the `TeamConfiguration`. The saved team is self-contained — it does not
hold references back to the archetype library. This ensures:

- A saved team file can be moved to another machine and works without needing
  the same archetype library
- If an archetype evolves later, existing saved teams are unaffected
- No resolution failures at execution time

### LLM-Generated Archetypes

When the LLM generates a team for an unknown problem, it may invent new agent
definitions that don't correspond to any existing archetype. These can be
extracted and saved as new archetypes for future reuse:

```python
result = generator.generate_team_from_llm(task=..., ...)
# result.config — full team (save as team)
# result.new_archetypes — new agent definitions invented by the LLM (save individually)
```

---

## Team Library & Storage

### `TeamLibrary`

The `TeamLibrary` loads team configurations from directories and provides
access by name:

```python
class TeamLibrary:
    """Loads and provides access to team configurations."""

    def list_teams(self) -> list[str]
    def get(self, name: str) -> TeamConfiguration | None
    def register(self, name: str, config: TeamConfiguration) -> None

    @classmethod
    def default(cls) -> TeamLibrary
        # Loads from <package>/templates/teams/

    @classmethod
    def from_directory(cls, path: Path) -> TeamLibrary
```

### Default Directory

The framework ships built-in teams and archetypes in a default templates
directory within the package:

```
<package>/templates/
  teams/                    # Complete team configs (agents + workflow)
    research_report.json
    code_review.json
    content_creation.json
  archetypes/               # Individual agent definitions (building blocks)
    researcher.json
    planner.json
    writer.json
    reviewer.json
    editor.json
    human_reviewer.json
```

`TeamLibrary.default()` and `ArchetypeLibrary.default()` load from these
directories. Developers can load additional directories via
`from_directory(path)` for their own teams and archetypes.

### Persistence

Teams and archetypes are persisted as JSON (or YAML) files using the existing
`TeamConfiguration.save_json()` / `save_yaml()` and the corresponding
`from_json_file()` / `from_yaml_file()` methods. The framework provides the
serialization primitives; the developer decides where to store files.

The `version` field on `TeamConfiguration` is a developer-managed reference
string. The framework does not enforce or track versioning.

---

## Dynamic Team Composition

The first step of any workflow is determining **which agents form the team and
how they collaborate**. Three modes are supported:

### Mode 1 — Template (Primary)

Load a pre-built team configuration from the `TeamLibrary`. Fast, reliable,
and deterministic.

### Mode 2 — Custom (Developer-Provided)

The developer supplies a complete `TeamConfiguration` (JSON/YAML). The
framework validates it against the schema, checks tool availability, and
builds the runnable team.

### Mode 3 — LLM-Generated (For Unknown Problems)

When no template fits, the developer can call `generate_team_from_llm()` to
delegate team design to an LLM. This is an **optional, one-time bootstrapping**
mechanism — the generated team is saved and reused on subsequent runs.

The generation process:

1. **Collect context** — Assemble into the prompt:
   - The developer's task description
   - The **available tool registry** (tool IDs, descriptions, input/output
     schemas) — so the LLM knows what agents *can* do
   - The **available model registry** (model IDs, capability profiles) — so
     the LLM can assign appropriate models to agents
   - The **archetype library** — fed as examples and building blocks
2. **Generate** — The LLM returns a `TeamConfiguration` dict plus a
   `capability_gaps` list and optionally `new_archetypes` for agent definitions
   it invented
3. **Validate** — Schema conformance, dangling agent/tool references, workflow
   consistency
4. **Return** — The framework returns a `TeamGenerationResult`; the developer
   decides whether to save, modify, or discard it

#### Capability Gaps

When the LLM generates a team, it must also report what it *could not* provide
given the available toolset. Each gap has a severity level that determines
framework behavior:

| Severity                 | Meaning                                        | Framework behavior                          |
| ------------------------ | ---------------------------------------------- | ------------------------------------------- |
| `blocking`               | Agent cannot function without this tool         | Reject the config; report what's needed     |
| `degraded`               | Agent works but quality/scope is reduced        | Warn; downgrade behavior type; proceed      |
| `functional_but_limited` | Agent works fine, just less polished output     | Log and proceed silently                    |

Example gap entry:

```json
{
  "agent_id": "case_researcher",
  "needed": "legal_database_search",
  "description": "Agent needs access to a legal case database to find relevant precedents. Without this, the agent will rely on general knowledge only.",
  "severity": "degraded",
  "fallback": "llm_only"
}
```

#### Team Generation Result

The output of LLM-generated team composition is wrapped in a
`TeamGenerationResult` that separates the runnable config from generation
metadata:

```python
class TeamGenerationResult(BaseModel):
    config: TeamConfiguration           # The runnable team definition
    capability_gaps: list[CapabilityGap] # What's missing from the toolset
    new_archetypes: list[AgentDefinition]# New agent types invented by the LLM
    generation_model: str               # Which LLM designed this team
```

This keeps `TeamConfiguration` clean — it remains valid for hand-authored
configs that have no gaps.

#### Approval Flow

The confirmation step is configurable:

| Setting                        | Behavior                                              |
| ------------------------------ | ----------------------------------------------------- |
| `auto_approve=False` (default) | Return the result for developer inspection before execution |
| `auto_approve=True`            | Skip confirmation when there are no `blocking` gaps; proceed directly |

#### Fallback Strategies

The LLM suggests fallback strategies per gap (it understands the domain
context); the framework validates that the suggested fallback is feasible
(e.g., `fallback: "llm_only"` is always valid; `fallback: "use_alternative_tool"`
is only valid if the alternative tool exists in the registry).

---

## Per-Agent Model Selection & Capability Requirements

Different agents may require different LLM providers and models based on their
task characteristics. Models have differentiated strengths — reasoning, writing,
coding, long-context handling, tool calling — and agents should be matched to
models that excel at their specific needs.

### Explicit Model Assignment

The `model` field on `AgentDefinition` already supports per-agent model
selection via explicit provider-prefixed names:

```json
{
  "id": "code_writer",
  "model": "anthropic:claude-sonnet-4-20250514",
  "role": "Code Writer"
}
```

This is the direct path when the user knows which model they want for each
agent.

### Declarative Model Requirements (Resolution at Build Time)

For LLM-generated teams and portable configurations, agents can declare **what
they need** instead of **which model to use**. A `model_requirements` field
expresses capability needs:

```json
{
  "id": "code_writer",
  "model_requirements": {
    "strengths": ["coding", "reasoning"],
    "supports_tool_calling": true,
    "min_context_window": 100000
  },
  "role": "Code Writer"
}
```

At build time, the framework resolves these requirements against the registered
model/provider registry and selects the best available match. This decouples
team definitions from specific model names — a config that says
`strengths: ["coding"]` works regardless of which providers the user has access
to.

### Model Requirements Schema

```json
{
  "model_requirements": {
    "strengths": ["reasoning", "coding", "writing", "analysis", "long_context"],
    "supports_tool_calling": false,
    "supports_structured_output": false,
    "min_context_window": null,
    "cost_tier": "standard"
  }
}
```

| Field                       | Type          | Description                                           |
| --------------------------- | ------------- | ----------------------------------------------------- |
| `strengths`                 | `list[str]`   | Desired model capabilities (e.g., "coding", "reasoning", "writing") |
| `supports_tool_calling`     | `bool`        | Whether the agent needs native function/tool calling  |
| `supports_structured_output`| `bool`        | Whether the agent needs guaranteed JSON output        |
| `min_context_window`        | `int \| null` | Minimum context window size in tokens                 |
| `cost_tier`                 | `str \| null` | Cost preference: "economy", "standard", "premium"     |

### Resolution Priority

When both `model` and `model_requirements` are set, `model` takes precedence
(explicit always wins). When only `model_requirements` is set, the framework
resolves at build time. When neither is set, the team-level or global default
model is used.

### Tier Variables

The existing tier variables (`$SMART_LLM`, `$FAST_LLM`) remain as a simpler
alternative to `model_requirements` for cases where the only distinction needed
is quality vs. speed.

---

---

[Next: Plugin Architecture >](04-plugins.md)
