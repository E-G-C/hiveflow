# Data Model: LLM Provider Plugin Architecture

**Date**: 2026-02-19 | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

## Existing Entities (No Changes)

These entities already exist and require **no modifications**:

### LLMMessage (dataclass)

```python
@dataclass
class LLMMessage:
    role: str           # "system", "user", "assistant", "tool"
    content: str
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
```

Location: `hiveflow/plugins/llm/__init__.py:23-31`

### LLMConfig (dataclass)

```python
@dataclass
class LLMConfig:
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 16000
    top_p: float = 1.0
    stop: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
```

Location: `hiveflow/plugins/llm/__init__.py:34-44`

### LLMResponse (dataclass)

```python
@dataclass
class LLMResponse:
    content: str
    model: str
    tool_calls: list[dict[str, Any]] | None = None
    usage: TokenUsage | None = None
    finish_reason: str = "stop"
```

Location: `hiveflow/plugins/llm/__init__.py:47-55`

### TokenUsage (dataclass)

```python
@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

Location: `hiveflow/plugins/llm/__init__.py:58-64`

## Existing Abstract Interfaces (No Changes)

### LLMProvider (abstract base class)

```python
class LLMProvider(BasePlugin):
    plugin_id: str              # abstract property
    description: str            # abstract property
    supports_streaming: bool    # default False
    supports_function_calling: bool  # default False
    supports_json_mode: bool    # default False
    supports_vision: bool       # default False

    async def chat(messages: list[LLMMessage], config: LLMConfig) -> LLMResponse  # abstract
    async def chat_stream(messages: list[LLMMessage], config: LLMConfig) -> AsyncIterator[str]  # default: yields chat().content
    def get_available_models() -> list[str]  # default: []
```

Location: `hiveflow/plugins/llm/__init__.py:67-147`

### LLMProviderRegistry

```python
class LLMProviderRegistry(PluginRegistry[LLMProvider]):
    entry_point_group = "hiveflow.llm"
    resolve_model(model_ref: str) -> tuple[LLMProvider, str]
```

Location: `hiveflow/plugins/llm/__init__.py:150-190`

## New Entity: AzureOpenAIProvider

### Class Definition

```python
class AzureOpenAIProvider(LLMProvider):
    plugin_id = "azure"
    description = "Azure OpenAI Service provider (Entra ID RBAC + API key)"
```

### Constructor Parameters

| Parameter | Type | Default | Source |
|-----------|------|---------|--------|
| `azure_endpoint` | `str | None` | `None` | Falls back to `AZURE_OPENAI_ENDPOINT` env var |
| `api_key` | `str | None` | `None` | Falls back to `AZURE_OPENAI_API_KEY` env var |
| `api_version` | `str` | `"2024-10-21"` | Latest stable Azure OpenAI API version |

### Authentication Decision Tree

```
backend = get_secret_backend()
Has backend.get_secret("AZURE_OPENAI_API_KEY") (or api_key param)?
  ├─ YES → Use API key auth (AsyncAzureOpenAI with api_key)
  └─ NO → Try RBAC auth
           ├─ azure-identity installed?
           │   ├─ YES → DefaultAzureCredential + get_bearer_token_provider
           │   └─ NO → Raise LLMAuthError with install command
           └─ DefaultAzureCredential succeeds?
               ├─ YES → Proceed with RBAC token
               └─ NO → Raise LLMAuthError referencing RBAC role + env vars
```

### Capability Flags

| Capability | Value | Reason |
|------------|-------|--------|
| `supports_streaming` | `True` | Azure OpenAI supports streaming |
| `supports_function_calling` | `True` | Azure OpenAI supports tools/functions |
| `supports_json_mode` | `True` | Azure OpenAI supports structured output |
| `supports_vision` | `True` | Azure OpenAI supports image inputs (GPT-4o deployments) |

### Internal State

| Field | Type | Description |
|-------|------|-------------|
| `_azure_endpoint` | `str | None` | Stored endpoint URL |
| `_api_key` | `str | None` | Stored API key (if provided) |
| `_api_version` | `str` | Azure API version string |
| `_client` | `Any | None` | Lazily initialized `AsyncAzureOpenAI` instance |

## Configuration Mapping

### Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure provider | Azure OpenAI resource endpoint URL |
| `AZURE_OPENAI_API_KEY` | Azure provider | API key (overrides RBAC) |
| `AZURE_TENANT_ID` | DefaultAzureCredential | Entra ID tenant for service principal |
| `AZURE_CLIENT_ID` | DefaultAzureCredential | Service principal client ID |
| `AZURE_CLIENT_SECRET` | DefaultAzureCredential | Service principal secret |
| `OPENAI_API_VERSION` | Azure provider (fallback) | Azure API version override |

### Model Reference Format

```
azure:<deployment-name>
```

Example: `azure:gpt-4o-eastus` where `gpt-4o-eastus` is the Azure deployment name (not the model name).

## Entity Relationships

```
HiveFlowConfig.resolve_model("$SMART_LLM")
  → "openai:gpt-4o"
  → LLMProviderRegistry.resolve_model("openai:gpt-4o")
  → (OpenAIProvider, "gpt-4o")

FallbackChain([(azure_provider, "gpt-4o-deployment"), (openai_provider, "gpt-4o")])
  → tries Azure first, falls back to OpenAI
```

## No Schema Migrations

This feature adds no database tables, no persistent state, and no schema changes. All provider state is in-memory.

## New Entity: LLMProviderError Hierarchy (FR-018)

### Base Exception

```python
class LLMProviderError(Exception):
    """Base exception for all LLM provider errors.

    All subclasses carry a human-readable message and optional provider_id.
    """

    def __init__(self, message: str, provider_id: str | None = None) -> None:
        self.provider_id = provider_id
        super().__init__(message)
```

Location: `hiveflow/plugins/llm/errors.py` (NEW)

### Subclasses

| Exception | Purpose | Transient? | Triggers Fallback? |
|-----------|---------|------------|-------------------|
| `LLMAuthError` | Auth/authorization failure (invalid key, missing RBAC role) | No | No — fail immediately |
| `LLMRateLimitError` | Rate limit or quota exhaustion | Yes | Yes |
| `LLMModelNotFoundError` | Unknown model or deployment | No | No — fail immediately |
| `LLMConnectionError` | Network, timeout, server errors (5xx) | Yes | Yes |

### Relationship to FallbackChain

The `FallbackChain` default `retry_on` changes from `(Exception,)` to `(LLMRateLimitError, LLMConnectionError)` per FR-019. Only transient errors cascade; auth and model-not-found errors fail immediately without trying the next provider.

### Streaming Error Behavior (FR-023)

When `chat_stream()` encounters an error mid-stream, partial content is discarded and a typed `LLMConnectionError` is raised. The error contract is identical to `chat()`.

## New Entity: SecretBackend (Protocol)

### Interface

```python
@runtime_checkable
class SecretBackend(Protocol):
    """Pluggable credential resolution interface (FR-017)."""

    def get_secret(self, key: str) -> str | None:
        """Resolve a secret by key name.

        Args:
            key: Secret identifier (e.g., "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT")

        Returns:
            Secret value or None if not found
        """
        ...
```

Location: `hiveflow/plugins/llm/secrets.py` (NEW)

### Default Implementation: EnvVarBackend

```python
class EnvVarBackend:
    """Default backend — reads from environment variables."""

    def get_secret(self, key: str) -> str | None:
        return os.environ.get(key)
```

### Global State

| Function | Description |
|----------|-------------|
| `get_secret_backend() -> SecretBackend` | Returns the active backend (default: `EnvVarBackend`) |
| `set_secret_backend(backend)` | Replaces the active backend globally |

### Usage by Providers

All providers use `get_secret_backend().get_secret(key)` instead of `os.environ.get(key)` directly. This enables custom secret stores (AWS SSM, Azure Key Vault, HashiCorp Vault) without modifying provider code.

## New Module: Observability (hiveflow/core/observability.py)

### structlog Configuration

```python
configure_logging() -> None
    # Configures structlog with:
    # - JSON renderer in production (HIVEFLOW_ENV=production)
    # - ConsoleRenderer in development (default)
    # - Bridges stdlib logging through structlog processors
```

### OTel Instrumentation

| Symbol | Type | Description |
|--------|------|-------------|
| `tracer` | `Tracer | None` | OTel tracer for `hiveflow.llm` (None if OTel not installed) |
| `meter` | `Meter | None` | OTel meter for `hiveflow.llm` (None if OTel not installed) |
| `llm_duration` | `Histogram | None` | `gen_ai.client.operation.duration` metric |
| `llm_token_usage` | `Counter | None` | `gen_ai.client.token.usage` metric |
| `_otel_enabled` | `bool` | Controlled by `HIVEFLOW_OTEL_ENABLED` env var |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HIVEFLOW_ENV` | `"development"` | Controls log format (dev=pretty, production=JSON) |
| `HIVEFLOW_OTEL_ENABLED` | `"false"` | Toggle OTel spans and metrics on/off |

## Terminology: `provider_id` vs `plugin_id`

Per clarification Q6, `provider_id` is the canonical term for LLM provider identification throughout the codebase. `plugin_id` remains as the abstract property on `BasePlugin` (used by the generic plugin registry), but all LLM-specific documentation, logs, and user-facing messages use `provider_id`.

In implementation, `LLMProvider.plugin_id` is the abstract property inherited from `BasePlugin`. A `provider_id` alias property may be added as a convenience that delegates to `plugin_id`.
