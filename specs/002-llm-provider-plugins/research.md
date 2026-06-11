# Research: LLM Provider Plugin Architecture

**Date**: 2026-02-19 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## R1: Azure OpenAI RBAC Authentication Pattern

### DefaultAzureCredential Chain

The `DefaultAzureCredential` from `azure-identity` tries credentials in this order:

1. **EnvironmentCredential** — service principal via `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (or certificate path)
2. **WorkloadIdentityCredential** — Azure Kubernetes workload identity
3. **ManagedIdentityCredential** — Azure VM / AKS / App Service managed identity
4. **SharedTokenCacheCredential** — Windows only, cached Microsoft app tokens
5. **AzureCLICredential** — `az login` session
6. **AzurePowerShellCredential** — `Connect-AzAccount` session
7. **AzureDeveloperCliCredential** — `azd auth login` session

This chain covers all acceptance scenarios in the spec:
- **US1-AS1** (service principal): EnvironmentCredential
- **US1-AS4** (managed identity on VM): ManagedIdentityCredential
- **US1-AS5** (developer `az login`): AzureCLICredential

### Token Provider Pattern

The OpenAI SDK's Azure client accepts an `azure_ad_token_provider` callable that returns a bearer token on demand. The `get_bearer_token_provider()` helper from azure-identity handles token caching and refresh automatically.

```python
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)
```

The scope `https://cognitiveservices.azure.com/.default` is the Azure Cognitive Services audience — required for all Azure OpenAI requests authenticated via Entra ID.

### Token Refresh

The `get_bearer_token_provider` handles refresh transparently. When the underlying token expires, the next call to the provider refreshes it. This satisfies SC-006 (sessions >60 minutes).

### RBAC Role

The user/identity must have the **"Cognitive Services OpenAI User"** role (or "Cognitive Services OpenAI Contributor") assigned on the Azure OpenAI resource. Propagation takes up to 5 minutes.

## R2: OpenAI SDK Azure Client API

### AzureOpenAI / AsyncAzureOpenAI Constructor

Key parameters:
- `azure_endpoint` — the resource URL (e.g., `https://my-resource.openai.azure.com/`)
- `api_version` — Azure API version (e.g., `"2024-10-21"`)
- `azure_ad_token_provider` — callable returning bearer token (for RBAC auth)
- `api_key` — static API key (for key-based auth)
- `azure_deployment` — optional default deployment name

Environment variable defaults:
- `AZURE_OPENAI_ENDPOINT` → `azure_endpoint`
- `AZURE_OPENAI_API_KEY` → `api_key`
- `OPENAI_API_VERSION` → `api_version`

### RBAC Initialization

```python
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)

client = AsyncAzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    azure_ad_token_provider=token_provider,
    api_version="2024-10-21",
)
```

### API Key Initialization

```python
from openai import AsyncAzureOpenAI

client = AsyncAzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version="2024-10-21",
)
```

### API Compatibility

`AzureOpenAI` / `AsyncAzureOpenAI` shares the same `.chat.completions.create()` method as the standard OpenAI client. This means:
- Streaming works identically (`stream=True`)
- Tool/function calling works identically
- JSON mode works identically (`response_format={"type": "json_object"}`)
- Vision works identically (image URLs in messages)

The `model` parameter in Azure = deployment name (not the model name). Users create a deployment and reference it as `azure:my-deployment-name`.

## R3: Entry Point Registration

### Current State

The `pyproject.toml` has an empty `[project.entry-points."hiveflow.llm"]` section with only comments. The existing OpenAI and Anthropic providers are functional but not discoverable via entry points.

### Required Changes

Register entries pointing to the provider classes:

```toml
[project.entry-points."hiveflow.llm"]
openai = "hiveflow.plugins.llm.openai_provider:OpenAIProvider"
anthropic = "hiveflow.plugins.llm.anthropic_provider:AnthropicProvider"
azure = "hiveflow.plugins.llm.azure_provider:AzureOpenAIProvider"
```

After `uv sync` (or `pip install -e .`), `get_llm_registry()` will auto-discover all three providers via `importlib.metadata.entry_points(group="hiveflow.llm")`.

### Discovery Flow

1. `get_llm_registry()` creates `LLMProviderRegistry(entry_point_group="hiveflow.llm")`
2. `discover()` calls `_discover_entry_points()`
3. For each entry point, `ep.load()` imports the class, instantiates it, calls `register()`
4. Failed imports are caught and logged — no crash (FR-014)

## R4: Existing Provider Architecture Analysis

### Pattern Summary

Both OpenAI and Anthropic providers follow the same pattern:
1. Lazy SDK import inside `_get_client()` — no import-time SDK dependency
2. `_get_client()` creates async client on first use, caches in `self._client`
3. Capability properties return `True` for all capabilities
4. `chat()` converts `LLMMessage` → API format, calls SDK, converts response → `LLMResponse`
5. `chat_stream()` uses SDK streaming, yields text chunks

### Azure Provider Design Implications

The Azure provider can follow the same pattern with two additions:
1. Auth selection logic in `__init__` / `_get_client()`: detect RBAC credentials vs API key
2. `DefaultAzureCredential` + `get_bearer_token_provider` for RBAC path
3. Fallback to `AZURE_OPENAI_API_KEY` if no RBAC credentials available

Since `AsyncAzureOpenAI` has the same `.chat.completions.create()` API as `AsyncOpenAI`, the `chat()` and `chat_stream()` methods can share the exact same message formatting logic. The Azure provider can reuse `OpenAIProvider._format_message()` (or duplicate the simple helper).

## R5: Error Handling Requirements

### Auth Failure Messaging

When neither RBAC credentials nor API key are available, the error message must:
1. Name both authentication methods
2. Reference "Cognitive Services OpenAI User" RBAC role
3. List the expected environment variables
4. Be actionable (tell the user what to do)

### Missing Provider Error

When `resolve_model("azure:deployment")` fails because azure isn't installed:
- Currently: `KeyError("Plugin 'azure' not found. Available: (none)")`
- Needed: Include install command `uv add hiveflow[llm-azure]`

The `get_or_raise()` in `PluginRegistry` already provides available plugins. We should enhance the error for known providers to suggest install commands.

## R6: structlog Migration (Clarification Q4 — Observability)

### Decision
Migrate LLM provider modules from `logging.getLogger(__name__)` to `structlog.get_logger()`. Configure structlog at app startup to render JSON in production and pretty-print in development. Keep stdlib logging as the output backend via `structlog.stdlib.ProcessorFormatter`.

### Rationale
`structlog` (>=24.4.0) is already a dependency but not yet integrated. All modules currently use `logging.getLogger(__name__)`. Migrating the LLM provider layer enables structured key-value events (`provider_id`, `model`, `latency_ms`, `token_count`) required by FR-015.

### Configuration Pattern

```python
# hiveflow/core/observability.py
import os, logging, structlog

def configure_logging() -> None:
    is_dev = os.environ.get("HIVEFLOW_ENV", "development") == "development"
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer = structlog.dev.ConsoleRenderer() if is_dev else structlog.processors.JSONRenderer()
    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(processors=[*shared_processors, renderer])
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
```

### Provider Usage

```python
import structlog
logger = structlog.get_logger()

# Emitted after each chat() call:
logger.info("llm.chat.complete", provider_id="openai", model="gpt-4o",
            latency_ms=234.5, prompt_tokens=150, completion_tokens=80)
```

### Coexistence
`structlog.stdlib.ProcessorFormatter` bridges structlog and stdlib. Existing `logging.getLogger(__name__)` calls outside the LLM layer continue to work unchanged.

### Alternatives Considered
- **Pure stdlib logging**: Rejected — structured events needed for FR-015.
- **Full codebase migration**: Out of scope — only LLM provider layer for now.
- **loguru**: Rejected — structlog already a dependency.

---

## R7: OpenTelemetry Minimal Integration (Clarification Q4 — Observability)

### Decision
Use `opentelemetry-api` as an optional dependency. When installed and enabled (`HIVEFLOW_OTEL_ENABLED=true`), emit OTel spans and metrics using GenAI semantic conventions. When not installed, all instrumentation calls are no-ops.

### Rationale
The `opentelemetry-api` provides a no-op tracer/meter when the full SDK is not installed. This means instrumentation code can always call `tracer.start_as_current_span()` without conditionals — if OTel is not configured, these are zero-cost no-ops. The constitution mandates OpenTelemetry as the tracing standard (2.6).

### Implementation Pattern

```python
# hiveflow/core/observability.py
import os
_otel_enabled = os.environ.get("HIVEFLOW_OTEL_ENABLED", "false").lower() == "true"

try:
    from opentelemetry import trace, metrics
    tracer = trace.get_tracer("hiveflow.llm")
    meter = metrics.get_meter("hiveflow.llm")
except ImportError:
    tracer = None
    meter = None

# Metrics (created once)
if meter and _otel_enabled:
    llm_duration = meter.create_histogram("gen_ai.client.operation.duration", unit="s")
    llm_token_usage = meter.create_counter("gen_ai.client.token.usage", unit="{token}")
else:
    llm_duration = None
    llm_token_usage = None
```

### GenAI Semantic Conventions

| Span Attribute | Description |
|----------------|-------------|
| `gen_ai.system` | Provider name ("openai", "azure", "anthropic") |
| `gen_ai.request.model` | Requested model |
| `gen_ai.response.model` | Actual model returned |
| `gen_ai.usage.input_tokens` | Prompt token count |
| `gen_ai.usage.output_tokens` | Completion token count |
| `gen_ai.request.temperature` | Temperature setting |
| `gen_ai.request.max_tokens` | Max tokens setting |

| Metric | Type | Unit |
|--------|------|------|
| `gen_ai.client.operation.duration` | Histogram | `s` |
| `gen_ai.client.token.usage` | Counter | `{token}` |

Span naming: `chat {provider_id}` (e.g., `chat openai`).

### Toggle pattern
Heavy OTel features (span creation, metric recording) controlled by `HIVEFLOW_OTEL_ENABLED`. structlog events always emit regardless — they are lightweight.

### Alternatives Considered
- **Always-on OTel**: Rejected per clarification Q4 (must be togglable).
- **`opentelemetry-instrumentation-openai`**: Rejected — provider-agnostic instrumentation at HiveFlow boundary preferred.

---

## R8: SecretBackend Interface (Clarification Q5 — Credential Sources)

### Decision
Define a `SecretBackend` Protocol with `get_secret(key: str) -> str | None`. Ship `EnvVarBackend` as default. Providers call `backend.get_secret("OPENAI_API_KEY")` instead of `os.environ.get()` directly.

### Rationale
FR-017 requires pluggable credential resolution. The simplest useful interface is a single method. Protocol (not ABC) supports structural subtyping — any class with `get_secret()` satisfies it without inheritance.

### Implementation

```python
# hiveflow/plugins/llm/secrets.py
from typing import Protocol, runtime_checkable
import os

@runtime_checkable
class SecretBackend(Protocol):
    def get_secret(self, key: str) -> str | None: ...

class EnvVarBackend:
    def get_secret(self, key: str) -> str | None:
        return os.environ.get(key)

_secret_backend: SecretBackend = EnvVarBackend()

def get_secret_backend() -> SecretBackend:
    return _secret_backend

def set_secret_backend(backend: SecretBackend) -> None:
    global _secret_backend
    _secret_backend = backend
```

### Provider usage

```python
from hiveflow.plugins.llm.secrets import get_secret_backend

class OpenAIProvider(LLMProvider):
    def _get_client(self):
        backend = get_secret_backend()
        api_key = self._api_key or backend.get_secret("OPENAI_API_KEY")
        ...
```

### Alternatives Considered
- **Key-value config file**: Rejected — plaintext creds violate FR-017.
- **ABC** instead of Protocol: Rejected — Protocol is lighter, supports duck typing.
- **Async `get_secret()`**: Deferred to v2. Remote stores can use `asyncio.to_thread()`.

---

## R9: Thread-Safety Analysis (Clarification Q2)

### Decision
Provider instances are thread-safe singletons. The registry returns the same instance to all callers.

### Rationale
The OpenAI and Anthropic Python SDKs use `httpx.AsyncClient` internally, which is thread-safe. A single provider instance shared across agents avoids unnecessary connection pool duplication.

### Key observations
- `AsyncOpenAI` creates one shared `httpx.AsyncClient` — thread-safe for concurrent requests
- `AsyncAnthropic` same pattern — shared `httpx.AsyncClient`
- `AsyncAzureOpenAI` inherits from `AsyncOpenAI` — same thread safety
- Provider `_get_client()` uses lazy init with simple `if self._client is None` check. In async code (single event loop), this is safe. For multi-threaded scenarios, a `threading.Lock` could be added but is not needed for the primary async use case.

### No changes needed
The current singleton pattern in `get_llm_registry()` already returns shared instances. No additional synchronization is required.

---

## R10: `from __future__ import annotations` Removal (Constitution 5.1)

### Decision
Remove `from __future__ import annotations` from all files modified in this feature.

### Files affected
- `hiveflow/plugins/llm/__init__.py` (line 12)
- `hiveflow/plugins/llm/anthropic_provider.py` (line 3)
- `hiveflow/core/registry.py` (line 8)
- `hiveflow/core/config.py` (line 6)

### Impact
All files use Python 3.11+ native `X | Y` syntax. The `TypeVar` bound in `registry.py` uses a string `"BasePlugin"` which doesn't require deferred evaluation. All forward references are already handled by runtime evaluation in Python 3.11+.

Safe to remove with no runtime changes.

---

## Sources

- [Azure OpenAI managed identity how-to](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/managed-identity)
- [azure-identity package reference](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity)
- [openai-python SDK README](https://github.com/openai/openai-python)
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [structlog documentation](https://www.structlog.org/)
- Existing codebase: `hiveflow/plugins/llm/`, `hiveflow/core/registry.py`, `pyproject.toml`

---

## R11: Typed Exception Hierarchy (FR-018, Session 2026-02-25)

### Decision
Define a rooted exception hierarchy in `hiveflow/plugins/llm/errors.py`: `LLMProviderError` (base) → `LLMAuthError`, `LLMRateLimitError`, `LLMModelNotFoundError`, `LLMConnectionError`. All exceptions carry `provider_id` and human-readable `message`.

### Rationale
FR-018 requires precise programmatic error handling. The FallbackChain (FR-019) needs to distinguish transient from permanent errors to decide whether to cascade. User code and middleware also benefit from `except LLMAuthError` rather than parsing error strings.

### Implementation

```python
# hiveflow/plugins/llm/errors.py

class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""

    def __init__(self, message: str, provider_id: str | None = None) -> None:
        self.provider_id = provider_id
        super().__init__(message)


class LLMAuthError(LLMProviderError):
    """Authentication or authorization failure (e.g., invalid API key, missing RBAC role)."""


class LLMRateLimitError(LLMProviderError):
    """Rate limit or quota exhaustion."""


class LLMModelNotFoundError(LLMProviderError):
    """Unknown model or deployment name."""


class LLMConnectionError(LLMProviderError):
    """Network, timeout, or server errors (5xx)."""
```

### Provider Exception Mapping

| SDK Exception | Maps To | Transient? |
|---------------|---------|------------|
| `openai.AuthenticationError` | `LLMAuthError` | No |
| `openai.RateLimitError` | `LLMRateLimitError` | Yes |
| `openai.NotFoundError` | `LLMModelNotFoundError` | No |
| `openai.APIConnectionError`, `openai.APITimeoutError` | `LLMConnectionError` | Yes |
| `openai.InternalServerError` (5xx) | `LLMConnectionError` | Yes |
| `anthropic.AuthenticationError` | `LLMAuthError` | No |
| `anthropic.RateLimitError` | `LLMRateLimitError` | Yes |
| `anthropic.NotFoundError` | `LLMModelNotFoundError` | No |
| `anthropic.APIConnectionError`, `anthropic.APITimeoutError` | `LLMConnectionError` | Yes |
| `azure.core.exceptions.ClientAuthenticationError` | `LLMAuthError` | No |
| `httpx.ConnectError`, `httpx.TimeoutException` | `LLMConnectionError` | Yes |

### Alternatives Considered
- **Single error with code enum**: Rejected — requires callers to switch on codes rather than catching specific types.
- **Return error dicts**: Rejected — breaks Python exception semantics, can't use `try/except`.

---

## R12: Transient-Only Fallback Behavior (FR-019, Session 2026-02-25)

### Decision
Change `FallbackChain` default `retry_on` from `(Exception,)` to `(LLMRateLimitError, LLMConnectionError)`. The `retry_on` parameter is preserved for caller override.

### Rationale
FR-019 says auth and model-not-found errors should fail immediately — they indicate configuration mistakes. The current default of `retry_on=(Exception,)` cascades on everything, masking config bugs. Defaulting to transient-only cascading surfaces permanent errors faster.

### Impact
- `build_fallback_chain()` will also use the new default.
- The `RetryProvider` default should similarly change to only retry transient errors.
- Existing callers who explicitly pass `retry_on` are unaffected.
- Callers relying on the `(Exception,)` default may see different behavior — this is intentional per FR-019.

### Alternatives Considered
- **New `TransientFallbackChain` subclass**: Rejected — adds unnecessary class. Changing the default is cleaner.
- **Configurable per-exception-type**: Rejected — overcomplicated. The typed hierarchy already enables this via `retry_on` override.

---

## R13: Capability Mismatch Workaround (FR-022, Session 2026-02-25)

### Decision
When an agent's provider lacks a required capability, log a structured warning and proceed with a prompt-based workaround. The agent does not fail and does not silently switch providers.

### Rationale
FR-022 requires degraded-but-functional behavior. Many local models can produce structured output when prompted correctly, even without native function-calling APIs. Failing would block useful workflows unnecessarily.

### Workaround Strategies

| Missing Capability | Workaround |
|-------------------|------------|
| Function/tool calling | Inject a JSON-schema prompt: "Respond with JSON matching this schema: ..." and parse the response |
| JSON mode | Add "Respond in valid JSON" to system prompt; use `json-repair` library for robustness |
| Vision | No workaround possible — log warning and pass image URLs anyway (provider may error) |
| Streaming | Fall back to non-streaming `chat()` and yield the full response as a single chunk |

### Implementation Location
Capability checks happen in the agent's tool-use loop (not in the provider itself). The provider honestly reports capabilities; the calling layer adapts.

### Alternatives Considered
- **Fail immediately**: Rejected — blocks useful workflows with capable-but-not-API-native models.
- **Silent provider switch**: Rejected — defeats per-agent model assignment intent.

---

## R14: Streaming Error Handling (FR-023, Session 2026-02-25)

### Decision
When `chat_stream()` encounters an error mid-stream, discard any partial content received and raise a typed `LLMConnectionError`. The error contract for streaming is identical to `chat()`.

### Rationale
Partial LLM output is typically unusable (cut off mid-sentence or mid-JSON). Preserving partial content adds complexity to the exception interface for minimal benefit. Consistent error handling across `chat()` and `chat_stream()` simplifies caller code.

### Implementation Pattern

```python
async def chat_stream(self, messages, config):
    client = self._get_client()
    try:
        stream = await client.chat.completions.create(..., stream=True)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except openai.APIConnectionError as exc:
        # Partial content already yielded is lost — caller discards
        raise LLMConnectionError(str(exc), provider_id=self.plugin_id) from exc
```

Note: Because `chat_stream()` is an async generator, the exception propagates to the caller's `async for` loop. The caller sees the exception after any partial chunks — they must handle this by discarding partial results and retrying via FallbackChain or directly.

### Alternatives Considered
- **Preserve partial in exception**: Rejected — adds `partial_content` attribute to exception, complicating error handling for edge-case benefit.
- **Auto-retry transparently**: Rejected — silent retry inside a generator is complex and hides latency from callers.

---

## R15: SecretBackend Routing for All Providers (FR-017 Updated, Session 2026-02-25)

### Decision
All providers — including the Azure provider's auth decision logic (API key vs. RBAC) — MUST resolve credentials through `get_secret_backend().get_secret(key)`, not `os.environ.get()` directly.

### Rationale
If a team uses a Key Vault backend, the Azure provider must respect it for consistency. The default `EnvVarBackend` makes this identical to `os.environ.get()`, so there's zero overhead for the common case.

### Azure Auth Decision via SecretBackend

```python
class AzureOpenAIProvider(LLMProvider):
    def _get_client(self):
        backend = get_secret_backend()
        api_key = self._api_key or backend.get_secret("AZURE_OPENAI_API_KEY")
        endpoint = self._azure_endpoint or backend.get_secret("AZURE_OPENAI_ENDPOINT")

        if not endpoint:
            raise LLMAuthError(
                "AZURE_OPENAI_ENDPOINT is required. ...",
                provider_id="azure",
            )

        if api_key:
            # API key auth
            client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_key=api_key, ...)
        else:
            # RBAC auth via DefaultAzureCredential
            ...
```

### Alternatives Considered
- **Direct env var reads for Azure only**: Rejected — inconsistent with FR-017. A Key Vault backend would be bypassed for Azure credentials.
