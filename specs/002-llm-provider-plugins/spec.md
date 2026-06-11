# Feature Specification: LLM Provider Plugin Architecture

**Feature Branch**: `002-llm-provider-plugins`
**Created**: 2026-02-19
**Status**: Draft
**Input**: User description: "LLM Provider Plugin Architecture with Azure RBAC — based on requirements/04-plugins.md"

## Clarifications

### Session 2026-02-19

- Q: Should the Ollama provider use the native API (`/api/chat`), OpenAI-compatible endpoint (`/v1/chat/completions`), or be dropped? → A: Drop dedicated Ollama provider (Option C). The existing OpenAI provider with `base_url` override covers Ollama. Add a stub/guideline for future native Ollama support.
- Q: Must LLM provider instances be thread-safe for concurrent use by multiple agents? → A: Yes — thread-safe singletons. One provider instance is shared across all agents; concurrent calls are allowed.
- Q: Should providers be initialized eagerly at startup or lazily on first use? → A: Lazy initialization. Entry points are scanned and provider classes registered at discovery, but SDK clients are created on first use. Keeps startup fast and avoids importing uninstalled optional dependencies.
- Q: What level of observability should provider operations emit? → A: Full observability (structured logs + OpenTelemetry-compatible span/metric hooks), but configurable — heavy features (tracing, detailed metrics) can be toggled on/off for troubleshooting without redeployment.
- Q: Where can provider credentials (API keys, endpoints) be sourced from? → A: Environment variables plus a pluggable secret backend interface. Env vars are the default; an extensible secrets interface allows integration with external stores (e.g., AWS SSM, Azure Key Vault) without hardcoding credentials in config files.
- Q: Should the canonical identifier for LLM providers be `plugin_id`, `provider_id`, or both? → A: Canonicalize on `provider_id` everywhere for LLM provider identification. Reserve `plugin_id` only if a generic plugin system beyond LLM providers exists.

### Session 2026-02-25

- Q: How should provider errors be structured? Should providers raise typed exception subclasses, a single error with a code enum, or return structured error dicts? → A: Typed exception hierarchy. Providers raise specific subclasses (`LLMAuthError`, `LLMRateLimitError`, `LLMModelNotFoundError`, `LLMConnectionError`) all inheriting from `LLMProviderError`. This lets fallback chains, middleware, and user code handle errors precisely.
- Q: Which errors should trigger fallback to the next provider in a FallbackChain? → A: Transient errors only. Rate limits (`LLMRateLimitError`), timeouts, and server errors (5xx / `LLMConnectionError`) trigger fallback. Auth errors (`LLMAuthError`) and model-not-found (`LLMModelNotFoundError`) fail immediately — they indicate configuration mistakes, not transient issues.
- Q: When a provider's lazy initialization fails mid-workflow, what should happen? → A: Fail the step and let the fallback chain handle it. The init failure raises a typed exception which the fallback chain can catch and cascade to the next provider. If no fallback is configured, the step fails with an actionable error message.
- Q: Should the SecretBackend interface be synchronous or asynchronous, and should credentials be cached? → A: Sync interface with optional TTL-based caching. The protocol is `get_secret(key: str) -> str | None`. Implementers can opt into a cache decorator with configurable TTL (e.g., 5 minutes). The default `EnvVarBackend` is inherently sync and instant, so caching is a no-op for the default case.
- Q: Should the Azure provider allow customizing which credential types DefaultAzureCredential tries? → A: No customization. Use `DefaultAzureCredential` as-is — it is the Azure-recommended approach and handles most scenarios correctly. Developers who need faster auth can set explicit service principal env vars, which `DefaultAzureCredential` tries first (skipping slow probes).
- Q: When an agent requires a capability (e.g., function calling) that its assigned provider doesn't support, what should happen? → A: Warn and proceed with prompt-based workaround. Log a structured warning, then attempt a prompt-based workaround (e.g., ask LLM to output JSON instead of native function calling). The agent continues with degraded fidelity rather than failing or silently switching providers.
- Q: When `chat_stream()` encounters an error mid-stream (e.g., connection drop after partial content), what should happen? → A: Discard partial content and raise a typed exception (`LLMConnectionError`). Partial LLM output is typically unusable. The FallbackChain or caller retries the full request from scratch. This keeps the error contract consistent with `chat()` behavior.
- Q: Should `chat_stream()` return structured events (with tool call deltas, usage) instead of plain `AsyncIterator[str]`? → A: Keep `AsyncIterator[str]` for this feature scope. Tool calls and usage metadata are only available via non-streaming `chat()`. Structured streaming events are a future enhancement outside this spec's scope.
- Q: Should the Azure provider's auth decision logic (API key vs. RBAC) route credential lookups through the pluggable `SecretBackend`, or read env vars directly? → A: Route all credential lookups through `SecretBackend`. This ensures a Key Vault backend can provide Azure credentials without env vars. The default `EnvVarBackend` makes this identical to direct reads for the common case.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Azure OpenAI with RBAC Authentication (Priority: P1)

An enterprise team deploys HiveFlow on Azure infrastructure. Their security policy mandates role-based access control via Microsoft Entra ID — no static API keys allowed. An operator configures the Azure OpenAI endpoint and tenant credentials, and agents seamlessly authenticate using the organization's identity system (service principal in CI/CD, managed identity on Azure VMs/AKS, or developer `az login` tokens locally).

**Why this priority**: The requirements document marks Azure RBAC as HIGH priority. Enterprise customers cannot adopt HiveFlow without Entra ID authentication — API keys are not permitted by many corporate security policies.

**Independent Test**: Can be fully tested by configuring `AZURE_OPENAI_ENDPOINT` and `AZURE_TENANT_ID`/`AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET`, running a single-agent workflow against an Azure OpenAI deployment, and verifying the agent produces a valid response. Also testable with `AZURE_OPENAI_API_KEY` as fallback.

**Acceptance Scenarios**:

1. **Given** `AZURE_OPENAI_ENDPOINT` and service-principal environment variables are set, **When** an agent runs with model `azure:my-deployment`, **Then** it authenticates via `DefaultAzureCredential` and completes the chat request successfully.
2. **Given** `AZURE_OPENAI_API_KEY` is set instead of RBAC credentials, **When** an agent runs with model `azure:my-deployment`, **Then** it falls back to API key authentication and completes the request.
3. **Given** neither RBAC credentials nor an API key are configured, **When** the Azure provider is initialized, **Then** a clear error message is raised explaining both authentication options and referencing the "Cognitive Services OpenAI User" RBAC role.
4. **Given** HiveFlow runs on an Azure VM with a managed identity assigned the "Cognitive Services OpenAI User" role, **When** an agent uses `azure:my-deployment`, **Then** authentication succeeds automatically without any credential environment variables.
5. **Given** a developer has run `az login`, **When** they run a local workflow with `azure:my-deployment`, **Then** authentication uses their Azure CLI token automatically.

---

### User Story 2 — Provider Plugin Discovery and Registration (Priority: P2)

A developer installs HiveFlow and expects the built-in LLM providers (OpenAI, Anthropic, Azure) to be automatically available without manual wiring. The framework discovers all installed provider plugins via Python entry points on startup and makes them accessible through the `provider:model` addressing convention.

**Why this priority**: The existing providers (OpenAI, Anthropic) are currently not registered as entry points — they are imported directly. Fixing this is foundational: every other provider story depends on the discovery mechanism working correctly.

**Independent Test**: Can be tested by calling `get_llm_registry()`, verifying all installed providers appear in `list_ids()`, and confirming `resolve_model("openai:gpt-4o")` returns the correct provider instance.

**Acceptance Scenarios**:

1. **Given** HiveFlow is installed with default dependencies, **When** the LLM registry discovers providers on startup, **Then** both `openai` and `anthropic` appear in the registry.
2. **Given** `hiveflow[llm-azure]` is installed, **When** the LLM registry discovers providers, **Then** `azure` also appears in the registry alongside `openai` and `anthropic`.
3. **Given** a workflow config references `model: "openai:gpt-4o"`, **When** the workflow engine resolves the model, **Then** it selects the OpenAI provider and passes `gpt-4o` as the model name.
4. **Given** a workflow config references an uninstalled provider (e.g., `google:gemini-2.0-flash`), **When** the workflow engine resolves the model, **Then** a clear error is raised naming the missing provider and suggesting an install command.

---

### User Story 3 — Mixed Cloud and Local Providers in One Workflow (Priority: P3)

A cost-conscious team wants to use a powerful cloud model for their primary "researcher" agent while running cheaper local models for simpler "reviewer" or "summarizer" agents. They configure per-agent model assignments in their workflow definition, mixing providers freely.

**Why this priority**: Per-agent model assignment already works via direct instantiation, but the `provider:model` resolution system must work end-to-end with auto-discovered providers for this to be seamless from configuration.

**Independent Test**: Can be tested by defining a two-agent workflow where one agent uses `openai:gpt-4o` and the other uses `openai:local-model` (pointed at a local llama.cpp endpoint), verifying both agents execute with their respective providers.

**Acceptance Scenarios**:

1. **Given** a workflow with agents assigned different models (`openai:gpt-4o`, `azure:my-deployment`, `openai:local-model`), **When** the workflow executes, **Then** each agent uses its assigned provider and model.
2. **Given** an agent's assigned provider fails, **When** a fallback chain is configured, **Then** the framework cascades to the next provider in the chain.
3. **Given** a workflow configuration uses model tier variables (`$SMART_LLM`, `$FAST_LLM`), **When** the engine resolves them, **Then** they expand to the configured `provider:model` values.

---

### Edge Cases

- What happens when Azure credentials expire mid-workflow? The provider should automatically refresh tokens via `DefaultAzureCredential`; the `azure_ad_token_provider` handles this transparently.
- What happens when multiple providers are installed for the same `provider_id`? The registry logs a warning and the last-registered provider wins (existing behavior from `PluginRegistry.register()`).
- What happens when the `llm-azure` extras are not installed but a workflow references `azure:*`? The Azure provider entry point fails gracefully at discovery time — logged and skipped. At resolution time, a clear "provider not installed" error names the package.
- What happens when `base_url` overrides point to a dead server? The provider raises a connection error with the URL in the message so the user can diagnose.
- What happens when a provider is referenced in config but its optional dependency is not installed? A clear error message names the missing package and provides the install command.
- What happens when `chat_stream()` encounters an error mid-stream (e.g., connection drop after partial content)? Partial content is discarded. A typed `LLMConnectionError` is raised, consistent with `chat()` error behavior. The FallbackChain or caller can retry the full request from scratch.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST register OpenAI and Anthropic providers as Python entry points so they are auto-discovered by the LLM registry on startup.
- **FR-002**: The framework MUST provide an Azure OpenAI provider plugin that authenticates via Microsoft Entra ID RBAC using `DefaultAzureCredential` as the default method.
- **FR-003**: The Azure provider MUST support API key authentication as a fallback when `AZURE_OPENAI_API_KEY` is set.
- **FR-004**: The Azure provider MUST use the OpenAI SDK's `AzureOpenAI` / `AsyncAzureOpenAI` client with `azure_ad_token_provider` for automatic token acquisition and refresh.
- **FR-005**: The Azure provider MUST support all capabilities that Azure OpenAI Service provides: streaming, function/tool calling, JSON mode, and vision.
- **FR-006**: The Azure provider MUST reference the "Cognitive Services OpenAI User" RBAC role in error messages when authentication fails.
- **FR-007**: The framework MUST declare `azure-identity>=1.19.0` as an optional dependency under the `llm-azure` extras group.
- **FR-008**: The `resolve_model()` function MUST correctly parse `provider:model` strings and return the matching provider from the registry.
- **FR-009**: When a referenced provider is not installed, the framework MUST raise a `KeyError` with a descriptive message including the provider name, available providers, and suggested install command. Note: `KeyError` is used for missing *providers* (registry lookup); `LLMModelNotFoundError` (FR-018) is raised by providers when the model/deployment name is unknown *within* an installed provider.
- **FR-010**: The framework MUST support per-agent model assignment via configuration, with each agent able to use a different provider.
- **FR-011**: The framework MUST support model tier variables (`$SMART_LLM`, `$FAST_LLM`, etc.) that resolve to `provider:model` strings from environment or configuration.
- **FR-012**: The framework MUST include a stub guideline documenting how to add new LLM provider plugins (e.g., Ollama, Google) so future contributors have a clear pattern to follow.
- **FR-013**: All provider plugins MUST declare their capabilities (streaming, function calling, JSON mode, vision) via boolean properties so the framework can query capabilities at runtime.
- **FR-014**: Provider plugin discovery MUST NOT crash the application — failed imports or missing dependencies MUST be logged and skipped gracefully.
- **FR-015**: Each provider `chat()` / `chat_stream()` call MUST emit a structured log event (via `structlog`) containing `provider_id`, model, latency, and token usage (when returned by the API). Errors and warnings (failed auth, timeouts, missing providers) MUST always be logged.
- **FR-016**: The framework MUST support OpenTelemetry-compatible tracing spans and metric hooks for provider calls, with a configuration toggle to enable/disable heavy observability features (tracing, detailed per-call metrics) without redeployment.
- **FR-017**: Provider credentials MUST be sourced via the pluggable `SecretBackend` interface (`get_secret(key: str) -> str | None`, synchronous). All providers — including the Azure provider's auth decision logic — MUST resolve credentials through this interface, not directly from `os.environ`. The default `EnvVarBackend` reads from environment variables. Implementers MAY use a TTL-based cache decorator. Credentials MUST NOT be stored in plaintext workflow configuration files.
- **FR-018**: Providers MUST raise typed exceptions from a hierarchy rooted at `LLMProviderError`. Required subclasses: `LLMAuthError` (authentication/authorization failures), `LLMRateLimitError` (rate limit / quota exhaustion), `LLMModelNotFoundError` (unknown model or deployment), `LLMConnectionError` (network/timeout/server errors). All exceptions MUST include a human-readable message and, where applicable, the `provider_id`.
- **FR-019**: The `FallbackChain` MUST cascade to the next provider only on **transient** errors (`LLMRateLimitError`, `LLMConnectionError`). Auth errors (`LLMAuthError`) and model-not-found errors (`LLMModelNotFoundError`) MUST fail immediately without fallback — they indicate configuration mistakes.
- **FR-020**: When lazy initialization of a provider fails mid-workflow, the failure MUST be surfaced as a typed exception. If a `FallbackChain` is configured, the chain handles the cascade. If not, the workflow step fails with an actionable error message.
- **FR-021**: The Azure provider MUST use `DefaultAzureCredential` without customization of which credential types are tried. No `exclude_*` parameters or custom credential chains are exposed.
- **FR-022**: When an agent's assigned provider lacks a required capability (e.g., function calling, vision), the framework MUST log a structured warning (via `structlog`) naming the missing capability and provider, then attempt a prompt-based workaround (e.g., instructing the LLM to produce JSON output instead of using native function calling). The agent MUST NOT fail or silently switch providers.
- **FR-023**: When `chat_stream()` encounters an error mid-stream, partial content MUST be discarded and a typed exception (`LLMConnectionError`) MUST be raised. The error contract for streaming MUST be consistent with `chat()` — callers handle both methods with the same exception types.

### Key Entities

- **LLMProvider**: A thread-safe abstraction over a specific LLM service. Identified by `provider_id` (the canonical identifier used in `provider:model` addressing, e.g., `openai`, `anthropic`, `azure`). Declares capabilities, exposes `chat()` and `chat_stream()` methods. A single instance is shared across all agents and must support concurrent calls safely (underlying SDK clients use `httpx` which is thread-safe).
- **LLMProviderRegistry**: Thread-safe singleton registry that discovers and indexes all available providers. Provider classes are registered eagerly at discovery (entry point scan), but SDK clients are instantiated lazily on first use. Supports lookup by `provider_id` and model reference resolution. Returns the same provider instance to all callers.
- **LLMConfig**: Per-request configuration (model name, temperature, max_tokens, tools, etc.) passed to the provider alongside messages.
- **LLMProviderError**: Base exception for all provider errors. Subclasses: `LLMAuthError`, `LLMRateLimitError`, `LLMModelNotFoundError`, `LLMConnectionError`.
- **FallbackChain**: An ordered list of (provider, model) pairs that cascades on **transient** errors only (`LLMRateLimitError`, `LLMConnectionError`). Auth and model-not-found errors fail immediately.
- **SecretBackend**: Pluggable interface for credential resolution. The default implementation reads from environment variables. Custom implementations can source credentials from external secret stores (AWS SSM, Azure Key Vault, HashiCorp Vault, etc.).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An Azure-hosted workflow authenticates and completes successfully using Entra ID RBAC without any API key configured.
- **SC-002**: All built-in providers (OpenAI, Anthropic, Azure) are auto-discovered via entry points — no manual imports required in user code.
- **SC-003**: A workflow mixing two or more different providers executes with each agent using its assigned provider.
- **SC-004**: A missing or misconfigured provider produces an actionable error message within 5 seconds (not a cryptic traceback).
- **SC-005**: All existing tests (409+) continue to pass after the provider plugin changes.
- **SC-006**: The Azure provider supports token refresh for long-running workflows — sessions lasting over 60 minutes do not fail due to expired credentials.

## Assumptions

- The Azure OpenAI Service deployment already exists and the caller's identity has the "Cognitive Services OpenAI User" role assigned. Provisioning Azure resources is out of scope.
- The `openai` Python SDK (>=1.0.0) supports `AzureOpenAI` with `azure_ad_token_provider` — this is a documented, stable feature of the SDK.
- Local model servers (Ollama, llama.cpp, vLLM, LM Studio) are served via the existing OpenAI provider's `base_url` override — no dedicated providers needed.
- Model tier variables (`$SMART_LLM`, `$FAST_LLM`) are resolved from environment variables or workflow-level configuration — the resolution mechanism already exists in the agent schema.
- The existing `FallbackChain` and `RetryProvider` are sufficient for resilience — no new retry/fallback patterns are needed.

## Scope Boundaries

**In scope:**
- Azure OpenAI provider with RBAC + API key fallback
- Registering existing providers (OpenAI, Anthropic) as entry points
- Entry-point-based discovery for all providers
- Pluggable `SecretBackend` interface for credential resolution (env var default)
- Stub guideline for adding future provider plugins (Ollama, Google, etc.)
- Tests for all new providers and the discovery mechanism

**Out of scope:**
- Dedicated Ollama provider (use OpenAI provider with `base_url` override instead)
- Google/Vertex AI, Perplexity, Mistral, Together, Fireworks, vLLM, LM Studio providers (future features)
- LiteLLM meta-provider
- Azure resource provisioning or role assignment
- Provider-specific rate limiting (handled by the existing `RateLimiter`)
- Web UI for provider management
- Structured streaming events (`LLMStreamEvent`) for tool call deltas — `chat_stream()` remains `AsyncIterator[str]`
- Runtime hot-reload of providers — discovery runs once on first registry access; adding new providers requires process restart and `uv sync`
