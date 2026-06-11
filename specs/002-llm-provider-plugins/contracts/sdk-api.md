# SDK API Contract: LLM Provider Plugins

**Date**: 2026-02-19 | **Plan**: [plan.md](plan.md) | **Data Model**: [../data-model.md](../data-model.md)

## Provider Discovery & Resolution

### Auto-Discovery (startup)

```python
from hiveflow.plugins.llm import get_llm_registry

registry = get_llm_registry()
# Returns singleton; calls discover() on first access
# All entry points under "hiveflow.llm" are loaded automatically
```

### List Available Providers

```python
registry.list_ids()
# → ["anthropic", "azure", "openai"]  (sorted alphabetically)
```

### Resolve a Model Reference

```python
provider, model_name = registry.resolve_model("openai:gpt-4o")
# provider: OpenAIProvider instance
# model_name: "gpt-4o"

provider, model_name = registry.resolve_model("azure:my-deployment")
# provider: AzureOpenAIProvider instance
# model_name: "my-deployment"
```

### Error: Unknown Provider

```python
registry.resolve_model("google:gemini-2.0-flash")
# Raises KeyError:
#   "Plugin 'google' not found. Available: anthropic, azure, openai.
#    Install with: uv add hiveflow[llm-google]"
```

### Error: Invalid Format

```python
registry.resolve_model("gpt-4o")
# Raises ValueError:
#   "Invalid model reference 'gpt-4o'.
#    Expected format: 'provider:model' (e.g., 'openai:gpt-4o')"
```

## Provider Usage

### Chat Completion

```python
from hiveflow.plugins.llm import LLMMessage, LLMConfig

messages = [
    LLMMessage(role="system", content="You are a helpful assistant."),
    LLMMessage(role="user", content="Hello!"),
]
config = LLMConfig(model="gpt-4o", temperature=0.7, max_tokens=1000)

response = await provider.chat(messages, config)
# response.content: str
# response.model: str
# response.usage: TokenUsage | None
# response.tool_calls: list[dict] | None
# response.finish_reason: str
```

### Streaming

```python
async for token in provider.chat_stream(messages, config):
    print(token, end="", flush=True)
```

### Capability Checks

```python
if provider.supports_function_calling:
    config.tools = [...]

if provider.supports_json_mode:
    config.response_format = {"type": "json_object"}

if provider.supports_vision:
    # Include image URLs in messages
    pass
```

## Azure-Specific Usage

### RBAC Authentication (default)

No code changes needed — just set environment variables:

```bash
export AZURE_OPENAI_ENDPOINT="https://my-resource.openai.azure.com/"
# One of: service principal, managed identity, or az login
export AZURE_TENANT_ID="..."
export AZURE_CLIENT_ID="..."
export AZURE_CLIENT_SECRET="..."
```

```python
provider, model = registry.resolve_model("azure:my-gpt4o-deployment")
response = await provider.chat(messages, LLMConfig(model=model))
```

### API Key Authentication (fallback)

```bash
export AZURE_OPENAI_ENDPOINT="https://my-resource.openai.azure.com/"
export AZURE_OPENAI_API_KEY="sk-..."
```

```python
# Same code — provider detects API key automatically
provider, model = registry.resolve_model("azure:my-gpt4o-deployment")
response = await provider.chat(messages, LLMConfig(model=model))
```

### Error: No Credentials

```python
# Neither RBAC env vars nor AZURE_OPENAI_API_KEY set
provider, model = registry.resolve_model("azure:my-deployment")
response = await provider.chat(messages, LLMConfig(model=model))
# Raises LLMAuthError:
#   "Azure OpenAI authentication failed. Configure one of:
#    1. RBAC: Set AZURE_OPENAI_ENDPOINT and assign 'Cognitive Services OpenAI User'
#       role to your identity (service principal, managed identity, or az login)
#    2. API Key: Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY
#    Install azure-identity: uv add hiveflow[llm-azure]"
```

## Error Handling (FR-018, FR-019, FR-023)

### Typed Exception Hierarchy

All provider errors are typed exceptions inheriting from `LLMProviderError`:

```python
from hiveflow.plugins.llm.errors import (
    LLMProviderError,
    LLMAuthError,
    LLMRateLimitError,
    LLMModelNotFoundError,
    LLMConnectionError,
)

try:
    response = await provider.chat(messages, config)
except LLMAuthError as e:
    # Invalid API key, missing RBAC role, expired credentials
    # e.provider_id: "openai", "azure", "anthropic"
    print(f"Auth failed for {e.provider_id}: {e}")
except LLMRateLimitError as e:
    # Rate limit or quota exhaustion — retryable
    print(f"Rate limited on {e.provider_id}: {e}")
except LLMModelNotFoundError as e:
    # Unknown model name or deployment
    print(f"Model not found on {e.provider_id}: {e}")
except LLMConnectionError as e:
    # Network, timeout, or server error — retryable
    print(f"Connection error on {e.provider_id}: {e}")
except LLMProviderError as e:
    # Catch-all for any provider error
    print(f"Provider error: {e}")
```

### Streaming Error Contract

Streaming errors are handled identically to `chat()`:

```python
try:
    async for token in provider.chat_stream(messages, config):
        print(token, end="", flush=True)
except LLMConnectionError:
    # Mid-stream error — partial content is discarded
    # Retry the full request (or let FallbackChain handle it)
    pass
```

### FallbackChain Transient-Only Behavior

The `FallbackChain` only cascades on transient errors (rate limits, connection errors). Auth and model-not-found errors fail immediately:

```python
from hiveflow.core.fallback import build_fallback_chain

chain = build_fallback_chain([
    (azure_provider, "gpt-4o-east"),
    (openai_provider, "gpt-4o"),
])

# Transient errors (rate limit, timeout) → cascade to next provider
# Auth errors, model-not-found → fail immediately, no cascade
response = await chain.chat(messages, config)
```

To override the default and cascade on all errors (not recommended):

```python
from hiveflow.core.fallback import FallbackChain

chain = FallbackChain(
    providers=[(azure_provider, "gpt-4o-east"), (openai_provider, "gpt-4o")],
    retry_on=(Exception,),  # Override: cascade on everything
)
```

## Model Tier Resolution

```python
from hiveflow.core.config import get_config

config = get_config()

# Resolve tier variable to provider:model string
model_ref = config.resolve_model("$SMART_LLM")
# → "openai:gpt-4o" (default)

# Then resolve to provider instance
provider, model = registry.resolve_model(model_ref)
```

## Fallback Chain

```python
from hiveflow.core.fallback import build_fallback_chain

azure_provider, _ = registry.resolve_model("azure:gpt-4o-east")
openai_provider, _ = registry.resolve_model("openai:gpt-4o")

chain = build_fallback_chain([
    (azure_provider, "gpt-4o-east"),
    (openai_provider, "gpt-4o"),
], max_retries_per_provider=2)

# Tries Azure first, retries twice on transient errors, then falls back to OpenAI
# Auth errors and model-not-found errors fail immediately (no cascade)
response = await chain.chat(messages, config)
```

## Per-Agent Model Assignment

In workflow YAML configuration:

```yaml
agents:
  researcher:
    model: "openai:gpt-4o"
    # ...
  reviewer:
    model: "azure:gpt-4o-deployment"
    # ...
  summarizer:
    model: "$FAST_LLM"  # resolves to openai:gpt-4o-mini
    # ...
```

Each agent resolves its model independently via `HiveFlowConfig.resolve_model()` → `LLMProviderRegistry.resolve_model()`.

## Secret Backend

### Default: Environment Variables

Providers resolve credentials through the `SecretBackend` interface. The default backend reads from environment variables — no configuration needed.

```python
# Default behavior — works out of the box
provider, model = registry.resolve_model("openai:gpt-4o")
# Internally calls get_secret_backend().get_secret("OPENAI_API_KEY")
# which defaults to os.environ.get("OPENAI_API_KEY")
```

### Custom Secret Backend

Replace the default backend to source credentials from external stores:

```python
from hiveflow.plugins.llm.secrets import set_secret_backend

class VaultBackend:
    """Load secrets from HashiCorp Vault."""

    def __init__(self, vault_client):
        self._client = vault_client

    def get_secret(self, key: str) -> str | None:
        try:
            return self._client.secrets.kv.v2.read_secret(path=key)["data"]["value"]
        except Exception:
            return None

set_secret_backend(VaultBackend(my_vault_client))

# Now all providers resolve credentials through Vault
provider, model = registry.resolve_model("openai:gpt-4o")
response = await provider.chat(messages, config)
```

### Query Active Backend

```python
from hiveflow.plugins.llm.secrets import get_secret_backend

backend = get_secret_backend()
# Returns the active SecretBackend instance (EnvVarBackend by default)
```

## Observability

### Structured Logging (always active)

Every `chat()` and `chat_stream()` call emits a structured log event via `structlog`:

```python
# Emitted automatically — no user action needed
# Example log output (development mode, pretty-printed):
#   2026-02-19T10:30:00Z [info] llm.chat.complete provider_id=openai model=gpt-4o
#                         latency_ms=234.5 prompt_tokens=150 completion_tokens=80

# Production mode (JSON):
#   {"event":"llm.chat.complete","provider_id":"openai","model":"gpt-4o",
#    "latency_ms":234.5,"prompt_tokens":150,"completion_tokens":80,"level":"info"}
```

Log format is controlled by `HIVEFLOW_ENV`:

```bash
export HIVEFLOW_ENV=development  # Pretty console output (default)
export HIVEFLOW_ENV=production   # JSON output
```

### OpenTelemetry Spans & Metrics (opt-in)

Enable OTel instrumentation with an environment variable:

```bash
export HIVEFLOW_OTEL_ENABLED=true
```

When enabled, each provider call emits:
- A **span** named `chat {provider_id}` with GenAI semantic convention attributes
- A **histogram** metric `gen_ai.client.operation.duration` (seconds)
- A **counter** metric `gen_ai.client.token.usage` (tokens)

```python
# No code changes needed — OTel is transparent
# Configure an OTel exporter (e.g., OTLP) separately via opentelemetry-sdk
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry import trace

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    SimpleSpanProcessor(ConsoleSpanExporter())
)

# Provider calls now emit spans automatically
response = await provider.chat(messages, config)
```

When `HIVEFLOW_OTEL_ENABLED` is not set or `false`, all OTel instrumentation is no-op (zero overhead).
