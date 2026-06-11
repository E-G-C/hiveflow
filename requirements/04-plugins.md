[< Back to Index](README.md)

---

## Tool Plugin Architecture

Tools are the primary extension point of the framework. Rather than bundling
tools into the core, they are treated as **self-contained plugins** that can be
developed independently and registered at runtime.

### Design Principles

- **Each tool is a standalone project** — with its own repository, dependencies,
  tests, and versioning. The core framework has zero knowledge of any specific
  tool.
- **A tool conforms to a contract** — every plugin implements a standard
  interface (e.g., a `ToolPlugin` base class or protocol) that exposes: a unique
  `plugin_id`, a human-readable `description` (used by the LLM to decide when to
  invoke it), an `input_schema`, an `output_schema`, and an `execute()` method.
- **Registration is automatic** — the framework discovers and loads plugins
  without manual wiring.

### Plugin Discovery Options

| Method                                  | How it works                                                                                                                                                                           | Pros                                                                                                                                            | Cons                                               |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Drop-in directory**                   | Place the plugin package in a `plugins/` folder; the framework scans and imports on startup                                                                                            | Simple, visual, no config needed                                                                                                                | Manual file management; version conflicts possible |
| **Python entry points** _(recommended)_ | Each plugin declares an entry point in its `pyproject.toml` under a group like `hiveflow.tools`; the framework discovers all installed plugins via `importlib.metadata.entry_points()` | Standard Python mechanism; install via `pip install hiveflow-tool-websearch`; dependencies resolved automatically; works with venvs, Docker, CI | Requires `pip install` step                        |
| **Explicit registry file**              | A `tools.yaml` or `tools.json` lists plugin module paths                                                                                                                               | Full control over load order and enablement                                                                                                     | Must be maintained manually                        |

**Recommended approach: Python entry points as the primary mechanism, with a
drop-in directory as a convenience override.**

### Plugin Interface

Each tool plugin exposes a minimal contract:

```
ToolPlugin (abstract base class, extends BasePlugin)
├── plugin_id: str            # unique identifier, e.g. "web_search" (inherited from BasePlugin)
├── description: str          # natural-language description for LLM tool selection
├── input_schema: dict        # JSON Schema describing expected input
├── output_schema: dict       # JSON Schema describing output shape
├── category: str             # "read_only" | "create" | "modify" | "deploy" | "destroy"
├── reversible: bool          # whether this tool supports undo/rollback
├── execute(input) -> output  # async; runs the tool
├── rollback(input) -> output # (optional) reverses a previous execute
├── to_llm_tool_spec() -> dict  # converts to OpenAI-style function calling spec
└── manifest.yaml             # optional metadata (author, version, dependencies, config)
```

A `manifest.yaml` at the plugin root can declare additional metadata:

```yaml
plugin_id: web_search
version: 1.2.0
description:
  "Search the web using multiple search engines and return ranked results."
author: team-hiveflow
category: read_only
reversible: false
config:
  api_key_env: SEARCH_API_KEY
  max_results: 10
dependencies:
  - httpx>=0.25
```

### Plugin Lifecycle

1. **Discovery** — On startup, the framework scans entry points + the `plugins/`
   directory and builds a **tool registry** (a dict of `plugin_id → ToolPlugin`
   instances).
2. **Validation** — Each discovered plugin is checked for interface compliance
   (required methods, valid schemas). Invalid plugins are logged and skipped,
   never crash the system.
3. **Injection** — When a team config references
   `"tools": ["web_search", "scraper"]` for an agent, the framework looks up
   those IDs in the registry and injects the tool instances into the agent at
   creation time.
4. **Execution** — The agent calls `tool.execute(input)` during its workflow
   step. Input/output are validated against the declared schemas.

### Benefits

- **Extensibility without core changes** — anyone can add a new tool by
  publishing a Python package or dropping a folder.
- **Independent testing and versioning** — each tool evolves on its own release
  cycle.
- **Selective installation** — production deployments only install the tools
  they need; no bloated dependency tree.
- **LLM-aware** — the `description` and `input_schema` fields can be fed
  directly to an LLM's function-calling / tool-use API, making tool selection a
  natural part of the agent's reasoning.

### Tool Approval (Inspired by Microsoft Agent Framework)

For tools that perform sensitive operations, the framework supports a
**tool-level approval pattern** that works in conjunction with workflow
checkpointing. This complements the existing `action_executor` agent-level
`action_policy` — it operates at the individual tool call level.

The framework currently supports four agent-level action policies on
`action_executor` agents:

| Policy              | Behavior                                                                 |
| ------------------- | ------------------------------------------------------------------------ |
| `auto`              | Execute tools immediately with audit trail                               |
| `require_approval`  | Pause after LLM proposes tools; wait for human approval before executing |
| `dry_run`           | Record proposed actions without executing                                |
| `confirm_on_error`  | Execute tools, pause only if execution fails                             |

Tool-level `requires_approval` adds a **per-tool** overlay on top of the
agent-level policy. When a tool is marked as requiring approval
(`requires_approval: true`), the workflow pauses before executing that tool
call, emits a `request_info` event with the tool name, input parameters, and
risk assessment, and waits for approval before proceeding.

**Precedence rules:** Tool-level `requires_approval` is the floor; agent-level
`action_policy` is an overlay. If **either** the tool requires approval or the
agent policy requires approval, approval is required. An `action_policy` of
`auto` does not bypass a tool's `requires_approval: true`. Conversely,
`action_policy: require_approval` applies to all tool calls regardless of the
individual tool's `requires_approval` setting.

```python
class ToolPlugin(BasePlugin):
    # ... existing fields ...

    @property
    def requires_approval(self) -> bool:
        """Whether this tool requires human approval before execution."""
        return False  # Default: no approval needed
```

The approval integrates with checkpointing — when approval is needed, the
workflow checkpoints its state so the process can be stopped and resumed after
the human responds (asynchronously, not necessarily in the same session).

### Tool Registry Serialization for LLM Context

When the framework generates teams via LLM (Mode 3), the tool registry contents
must be serialized into the generation prompt so the LLM knows what's available.
The `ToolRegistry` provides a `describe()` method that produces a compact
summary:

```python
class ToolRegistry:
    def describe(self) -> list[dict[str, Any]]:
        """Serialize all registered tools into a compact summary for LLM prompts.

        Returns a list of dicts with: plugin_id, description, category,
        reversible, input_schema (simplified).
        """
```

This summary is included in the LLM generation context alongside the model
registry and archetype library.

### Input/Output Schema Validation

Tool input and output are optionally validated against the declared JSON
schemas during execution. This catches malformed LLM tool calls early:

```python
engine = WorkflowEngine(
    workflow_steps=steps,
    validate_tool_io=True,  # Default: False
)
```

When enabled, schema validation failures are reported as structured errors
(not exceptions), allowing the agent to self-correct.

### Extended Tool Categories (New in v2)

Beyond research/data-gathering tools, the framework now supports:

| Category           | Example Tools                                           |
| ------------------ | ------------------------------------------------------- |
| **Search**         | web_search, arxiv, database_query, log_query            |
| **Scraping**       | web_scraper, pdf_extractor, api_fetcher                 |
| **Code**           | code_editor, terminal, test_runner, linter, git         |
| **Infrastructure** | kubernetes, cloud_deploy, ci_cd, terraform              |
| **Communication**  | email, slack, teams, webhook, pagerduty                 |
| **Data**           | sql_query, spreadsheet, csv_parser, data_visualizer     |
| **File I/O**       | file_read, file_write, s3_upload, blob_storage          |
| **Monitoring**     | metrics_query, health_check, trace_viewer, alertmanager |

---

## LLM Provider Plugin Architecture

LLM providers are the backbone of every agent. Like tools, they follow the
**plugin architecture** — the core framework defines an abstract interface, and
each provider is a separate, independently installable package.

### Provider Interface

```
LLMProvider (abstract base class, extends BasePlugin)
├── plugin_id: str                    # unique provider identifier (inherited from BasePlugin)
├── provider_id: str                  # convenience alias for plugin_id
├── description: str                  # human-readable description
├── supports_streaming: bool          # whether stream=True is supported
├── supports_function_calling: bool   # whether tool/function calling is supported
├── supports_json_mode: bool          # whether structured JSON output is supported
├── supports_vision: bool             # whether image inputs are supported
├── chat(messages, config) -> LLMResponse  # async completion returning structured response
├── chat_stream(messages, config) -> AsyncIterator[str]  # streaming completion
├── get_available_models() -> list[str] # list models this provider can serve
└── manifest.yaml                       # metadata, dependencies, config
```

The `chat()` method returns an `LLMResponse` dataclass containing `content`,
`model`, `tool_calls`, `usage` (token counts), and `finish_reason`. The
structured return type is required because agents depend on `tool_calls` for
tool-use loops and `usage` for cost tracking.

The `config` parameter is an `LLMConfig` dataclass accepting `model`,
`temperature`, `max_tokens`, `top_p`, `stop`, `tools` (list of tool specs),
`response_format`, and `extra` (provider-specific overrides).

### Provider Addressing Convention

All model references throughout the framework use the `provider:model` format:

```
openai:gpt-4o
azure:gpt-4o-deployment-name
ollama:llama3.3
llamacpp:models/mistral-7b.gguf
google:gemini-2.0-flash
anthropic:claude-sonnet-4-20250514
perplexity:sonar-pro
litellm:together_ai/meta-llama/Llama-3.3-70B
```

The part before `:` selects the provider plugin; the part after `:` is passed to
the provider to resolve the specific model.

### Built-in Provider Plugins

#### Cloud Providers

| Provider         | Package                   | API / SDK                          | Notes                                       |
| ---------------- | ------------------------- | ---------------------------------- | ------------------------------------------- |
| **OpenAI**       | `hiveflow-llm-openai`     | OpenAI API (`openai` SDK)          | Default provider; GPT-4o, o3, etc.          |
| **Azure OpenAI** | `hiveflow-llm-azure`      | Azure OpenAI Service               | Enterprise; deployment-name based routing; RBAC via Microsoft Entra ID (see [Azure Authentication](#azure-authentication)) |
| **Anthropic**    | `hiveflow-llm-anthropic`  | Anthropic API                      | Claude models                               |
| **Google**       | `hiveflow-llm-google`     | Vertex AI / Gemini API             | Gemini models                               |
| **Perplexity**   | `hiveflow-llm-perplexity` | Perplexity API (OpenAI-compatible) | Sonar models with built-in search grounding |
| **Mistral**      | `hiveflow-llm-mistral`    | Mistral API                        | Mistral / Codestral models                  |
| **Together**     | `hiveflow-llm-together`   | Together API                       | Open-source model hosting                   |
| **Fireworks**    | `hiveflow-llm-fireworks`  | Fireworks API                      | Fast open-source model inference            |

#### Local Providers

| Provider      | Package                 | Runtime                              | Notes                                         |
| ------------- | ----------------------- | ------------------------------------ | --------------------------------------------- |
| **Ollama**    | `hiveflow-llm-ollama`   | Ollama server (localhost)            | Easiest local setup; pull-and-run models      |
| **llama.cpp** | `hiveflow-llm-llamacpp` | llama-cpp-python bindings            | Direct GGUF model loading; no server required |
| **vLLM**      | `hiveflow-llm-vllm`     | vLLM server                          | High-throughput local/self-hosted inference   |
| **LM Studio** | `hiveflow-llm-lmstudio` | LM Studio server (OpenAI-compatible) | Desktop app with model management UI          |

#### Meta / Proxy Providers

| Provider    | Package                | Notes                                                                                            |
| ----------- | ---------------------- | ------------------------------------------------------------------------------------------------ |
| **LiteLLM** | `hiveflow-llm-litellm` | Universal proxy supporting 100+ providers via a single interface; useful as a catch-all fallback |

### Discovery & Registration

LLM providers use the same plugin discovery mechanism as tools:

- **Python entry points** under the `hiveflow.llm` group (primary)
- **Drop-in directory** at `providers/` (convenience for local development)

```toml
# Example pyproject.toml for hiveflow-llm-ollama
[project.entry-points."hiveflow.llm"]
ollama = "hiveflow_llm_ollama:OllamaProvider"
```

Installation: `pip install hiveflow-llm-ollama`

### Provider-Specific Configuration

Each provider may require its own configuration (API keys, endpoints, model
paths). These are resolved via environment variables, typically using each
provider SDK's standard variable names. The framework's `SecretBackend`
protocol (default: `EnvVarBackend`) reads from `os.environ`; custom backends
can be injected via `set_secret_backend()` for vault or managed-secret
integration:

| Provider     | Key Environment Variables                                            |
| ------------ | -------------------------------------------------------------------- |
| OpenAI       | `OPENAI_API_KEY`                                                     |
| Azure OpenAI | `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION`; RBAC (default): `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`; API key fallback: `AZURE_OPENAI_API_KEY` |
| Anthropic    | `ANTHROPIC_API_KEY`                                                  |
| Google       | `GOOGLE_API_KEY` or `GOOGLE_APPLICATION_CREDENTIALS`                 |
| Perplexity   | `PERPLEXITY_API_KEY`                                                 |
| Ollama       | `OLLAMA_BASE_URL` (default: `http://localhost:11434`)                |
| llama.cpp    | `LLAMACPP_MODEL_PATH` (path to `.gguf` file)                         |
| LiteLLM      | Inherits keys from underlying provider                               |

### Capability Negotiation

Not all providers support the same features. The framework queries provider
capabilities at registration time and respects them during execution. Each
provider exposes boolean capability properties (`supports_streaming`,
`supports_function_calling`, `supports_json_mode`, `supports_vision`):

| Capability                | Providers that support it                            |
| ------------------------- | ---------------------------------------------------- |
| **Streaming**             | All cloud providers, Ollama, vLLM                    |
| **Function/tool calling** | OpenAI, Azure, Anthropic, Google, Mistral            |
| **JSON mode**             | OpenAI, Azure, Anthropic, Google                     |
| **Vision (image input)**  | OpenAI, Azure, Anthropic, Google                     |
| **Large context (128k+)** | OpenAI (GPT-4o), Anthropic (Claude), Google (Gemini) |

When an agent requires a capability the assigned provider doesn't support (e.g.,
function calling on Ollama), the framework can either:

1. **Warn** and proceed with a prompt-based workaround (e.g., ask the LLM to
   output JSON instead of using native function calling)
2. **Fall back** to a provider that supports the capability (via the LLM
   fallback chain)

### Azure Authentication

> **Priority: HIGH** — Azure AI Foundry (formerly Azure OpenAI Service) MUST
> support Role-Based Access Control (RBAC) via Microsoft Entra ID as the
> **primary and recommended** authentication method. API key authentication is
> supported only as a fallback.

#### Requirements

1. **Microsoft Entra ID (RBAC) — default auth method.**
   The Azure provider MUST authenticate using **Azure Identity**
   (`azure-identity` SDK) with the `DefaultAzureCredential` chain. This covers:
   - **Service Principal** — `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
     `AZURE_CLIENT_SECRET` environment variables (CI/CD, server deployments).
   - **Managed Identity** — automatic when running on Azure infrastructure (App
     Service, AKS, Azure Functions, VMs with managed identity enabled). No
     credentials needed.
   - **Azure CLI / Developer credentials** — `az login` token for local
     development.

2. **Required Azure RBAC role.**
   The identity (user, service principal, or managed identity) MUST be assigned
   the **Cognitive Services OpenAI User** role
   (`Microsoft.CognitiveServices/accounts/deployments/read` +
   `Microsoft.CognitiveServices/accounts/deployments/completions/action`) on the
   Azure AI Foundry resource. The provider documentation and error messages
   MUST reference this role by name.

3. **Token credential integration with the OpenAI SDK.**
   The provider MUST use `openai.AzureOpenAI` (or `AsyncAzureOpenAI`) with
   `azure_ad_token_provider` parameter for automatic token acquisition and
   refresh via `azure.identity.get_bearer_token_provider()`.

4. **API key fallback.**
   When `AZURE_OPENAI_API_KEY` is set, the provider MUST fall back to API key
   authentication. When neither RBAC credentials nor an API key are available,
   the provider MUST raise a clear error explaining both options.

5. **Configuration.**
   Required environment variables:

   | Variable                  | Required | Description                                   |
   | ------------------------- | -------- | --------------------------------------------- |
   | `AZURE_OPENAI_ENDPOINT`   | Yes      | Azure resource endpoint URL                   |
   | `OPENAI_API_VERSION`    | No       | API version (default: `2024-10-21`)           |
   | `AZURE_TENANT_ID`         | RBAC     | Microsoft Entra tenant ID                     |
   | `AZURE_CLIENT_ID`         | RBAC     | Service principal / managed identity client ID|
   | `AZURE_CLIENT_SECRET`     | RBAC*    | Service principal secret (*not needed for managed identity) |
   | `AZURE_OPENAI_API_KEY`    | Fallback | API key (used only when RBAC is not configured)|

6. **Auth method selection logic.**

   ```
   if AZURE_OPENAI_API_KEY is set:
       use API key authentication
   else:
       use DefaultAzureCredential (RBAC)
       # Automatically picks up service principal, managed identity,
       # or developer credentials in that order
   ```

7. **Dependencies.**
   The `azure-identity` package is required for RBAC. It MUST be declared as:
   ```toml
   llm-azure = ["azure-identity>=1.19.0", "openai>=1.0.0"]
   ```

### Per-Agent Provider Assignment

The team config supports per-agent model assignment that resolves through the
provider plugin system:

```json
{
  "agents": [
    { "id": "researcher", "model": "$SMART_LLM" },
    { "id": "reviewer", "model": "ollama:llama3.3" },
    { "id": "writer", "model": "anthropic:claude-sonnet-4-20250514" },
    { "id": "summarizer", "model": "llamacpp:models/phi-3-mini.gguf" }
  ]
}
```

This allows mixing cloud and local models in the same workflow — e.g., using a
powerful cloud model for writing while running a fast local model for review or
summarization to reduce costs.

**Provider resolution:** When building agents from a team config, the framework
MUST resolve each agent's `model` reference individually through
`LLMProviderRegistry.resolve_model()`. Each agent receives its own provider
instance based on the `provider:model` prefix. Tier variables (`$SMART_LLM`,
`$FAST_LLM`, `$STRATEGIC_LLM`) are expanded via `HiveFlowConfig.resolve_model()`
before provider resolution. The current `TeamGenerator.build()` accepts a
single `llm_provider` parameter; this MUST be enhanced to support per-agent
provider resolution when agents reference different providers.

### Model Capability Registry

To support declarative `model_requirements` on agents (see
[Agents & Teams](03-agents-and-teams.md#per-agent-model-selection--capability-requirements)),
the provider registry exposes per-model capability metadata.

Each provider reports capabilities per model:

```python
@dataclass
class ModelCapability:
    model_id: str                       # e.g. "gpt-4o"
    context_window: int                 # e.g. 128000
    supports_tool_calling: bool
    supports_structured_output: bool
    supports_streaming: bool
    supports_vision: bool
    strengths: list[str]                # e.g. ["reasoning", "coding"]
    cost_tier: str                      # "economy" | "standard" | "premium"
```

The `LLMProviderRegistry` provides a resolution method:

```python
class LLMProviderRegistry:
    def resolve_model_requirements(
        self,
        requirements: ModelRequirements,
    ) -> tuple[LLMProvider, str]:
        """Find the best available model matching the given requirements.

        Checks all registered providers and their models, scores them
        against the requirements, and returns the best match.
        """
```

**Phase 1:** Simple matching on existing capability flags
(`supports_function_calling`, `supports_streaming`, etc.) and provider-level
metadata. **Phase 2:** Per-model granularity with `ModelCapability` dataclass.

### MCP Integration (Model Context Protocol)

The Model Context Protocol (MCP) is becoming a standard for tool discovery
and invocation. The framework supports MCP as a tool source alongside native
`ToolPlugin` implementations.

An MCP server exposes tools that can be automatically registered in the tool
registry:

```python
class MCPToolBridge(ToolPlugin):
    """Bridges an MCP server's tools into the HiveFlow tool registry."""

    def __init__(self, server_url: str, tool_name: str):
        self._server_url = server_url
        self._tool_name = tool_name

    @property
    def plugin_id(self) -> str:
        return f"mcp:{self._tool_name}"
```

Configuration:

```json
{
  "mcp_servers": [
    {
      "url": "http://localhost:3000/mcp",
      "tools": ["web_search", "file_read"]
    }
  ]
}
```

The framework discovers tools from configured MCP servers and registers them
as regular `ToolPlugin` instances. Agents use MCP tools the same way they use
native tools — the bridge is transparent.

**Implementation phase:** Future. The plugin interface is designed to
accommodate MCP tools without changes; only the bridge implementation is needed.

### Agent Middleware (Inspired by Microsoft Agent Framework)

Middleware provides a composable way to intercept and modify agent behavior
without changing the agent implementation. Middleware functions wrap the
agent's execution, operating on the input state and/or output state.

```python
class AgentMiddleware(Protocol):
    """Intercepts agent execution for cross-cutting concerns."""

    async def __call__(
        self,
        agent: Agent,
        state: dict[str, Any],
        next_fn: Callable,
    ) -> dict[str, Any]:
        """Process the agent call, optionally modifying input/output.

        Args:
            agent: The agent being invoked
            state: Input state to the agent
            next_fn: Calls the next middleware or the agent itself

        Returns:
            Modified output state
        """
```

Middleware is registered on the workflow engine and applied to all agents in
order:

```python
engine = WorkflowEngine(
    workflow_steps=steps,
    middleware=[
        logging_middleware,     # Log all agent inputs/outputs
        cost_tracking_middleware,  # Track token usage
        validation_middleware,    # Validate state schema
    ],
)
```

Use cases:
- **Logging** — Log every agent invocation without modifying agents
- **Cost tracking** — Accumulate token usage across all agents
- **State validation** — Enforce `state_schema` read/write boundaries
- **Rate limiting** — Throttle agent calls
- **Input/output transformation** — Normalize or sanitize data

**Implementation phase:** Phase 2. The existing `on_event` callback handles
basic observability; middleware adds pre/post interception of the execution
itself.

---

---

[Next: Data Processing & State Management >](05-data-processing.md)
