# Implementation Plan: LLM Provider Plugin Architecture

**Branch**: `002-llm-provider-plugins` | **Date**: 2026-02-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-llm-provider-plugins/spec.md`

## Summary

Extend HiveFlow's LLM plugin system with entry-point-based auto-discovery for all providers, add a new Azure OpenAI provider with Microsoft Entra ID RBAC authentication (+ API key fallback), introduce structured logging via `structlog`, configurable OpenTelemetry observability hooks, and a pluggable `SecretBackend` interface for credential resolution. The existing OpenAI and Anthropic providers are registered as entry points (currently only placeholder comments exist in pyproject.toml). All providers are thread-safe singletons with lazy SDK client initialization. Additionally: introduce a typed exception hierarchy (`LLMProviderError` → `LLMAuthError`, `LLMRateLimitError`, `LLMModelNotFoundError`, `LLMConnectionError`), enforce transient-only fallback in `FallbackChain`, handle capability mismatches via warn-and-workaround, and ensure all credential lookups route through `SecretBackend`.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations` per constitution)
**Primary Dependencies**: openai >=1.52.0, anthropic >=0.39.0, azure-identity >=1.19.0 (optional, `llm-azure` extras), pydantic >=2.9.2, structlog >=24.4.0, opentelemetry-api (optional, new)
**Storage**: N/A (in-memory provider registry singleton)
**Testing**: pytest + pytest-asyncio (existing ~20 test files, async auto mode)
**Target Platform**: Cross-platform Python library (Linux, macOS, Windows)
**Project Type**: Single Python package (`hiveflow/`)
**Performance Goals**: Provider error messages within 5 seconds (SC-004); token refresh for sessions >60 min (SC-006)
**Constraints**: Thread-safe singletons; lazy SDK client init; no plaintext creds in config files; core modules zero LLM SDK imports at import time
**Scale/Scope**: 3 built-in providers (OpenAI, Anthropic, Azure), extensible via entry points

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*
*Post-design re-check (2026-02-25): All PASS. Typed exception hierarchy (FR-018) aligns with 2.7 Fail Loudly. Transient-only fallback (FR-019) aligns with 2.7 Recover Gracefully. SecretBackend routing for all providers (FR-017 updated) aligns with 2.3. Capability mismatch warn-and-workaround (FR-022) aligns with 2.2 Progressive Disclosure. No new violations introduced.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| 2.1 | Configuration Over Code | PASS | Providers are selected via `provider:model` strings in YAML config. No user code needed. |
| 2.2 | Progressive Disclosure | PASS | Default tier variables (`$SMART_LLM` = `openai:gpt-4o`) work out of box. Azure is opt-in via extras. |
| 2.3 | Explicit State, No Magic | PASS | Registry is an explicit singleton. Credentials from env vars or SecretBackend — no hidden sources. |
| 2.4 | Plugin Architecture | PASS | This feature directly implements the constitution's plugin architecture for model providers. Entry point group `hiveflow.llm` already declared. |
| 2.5 | Backward Compatibility | PASS | Existing direct imports continue to work. Entry points are additive. Existing `plugin_id` property preserved on `BasePlugin`; `provider_id` is a canonical alias for LLM providers. |
| 2.6 | Observability Built In | PASS | FR-015 (structlog events) and FR-016 (OTel spans/metrics) implement this principle directly. |
| 2.7 | Fail Loudly, Recover Gracefully | PASS | Actionable error messages (FR-006, FR-009). FallbackChain + RetryProvider for recovery. |
| 3.1 | Core zero LLM SDK dependency | PASS | Lazy imports in providers. Entry points load classes, not SDK modules. |
| 3.2 | Plugin rules | PASS | No global state at import. Dependencies declared. Graceful skip on missing deps. |
| 5.1 | No `from __future__ import annotations` | VIOLATION | Existing files `llm/__init__.py`, `anthropic_provider.py`, `registry.py`, `config.py` use it. Must fix as part of this feature. |
| 5.2 | Package management via uv | PASS | All deps in pyproject.toml. `uv add` for installs. |
| 5.3 | Prefer Microsoft libraries | PASS | Azure provider uses `azure-identity`. OTel aligns with Azure Monitor. |
| 5.4 | Async First | PASS | All provider methods are `async`. SDK clients are `AsyncOpenAI`, `AsyncAnthropic`, `AsyncAzureOpenAI`. |

**Gate result**: PASS with one pre-existing violation to fix.

## Project Structure

### Documentation (this feature)

```text
specs/002-llm-provider-plugins/
├── plan.md              # This file
├── research.md          # Phase 0: Technology research
├── data-model.md        # Phase 1: Entity definitions
├── quickstart.md        # Phase 1: Developer quickstart (QV-1 through QV-10)
├── contracts/           # Phase 1: API contracts
│   ├── sdk-api.md       # SDK API contract (discovery, resolution, auth, observability, secrets)
│   └── provider-dev.md  # Provider development guideline (FR-012)
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── registry.py          # MODIFY: Remove `from __future__`, no logic changes
│   ├── config.py            # MODIFY: Remove `from __future__`, no logic changes
│   ├── fallback.py          # MODIFY: Default retry_on to transient exceptions only (FR-019)
│   └── observability.py     # NEW: structlog setup + OTel instrumentation helpers
├── plugins/
│   └── llm/
│       ├── __init__.py          # MODIFY: Remove `from __future__`, add `provider_id` alias, export SecretBackend
│       ├── errors.py            # NEW: LLMProviderError hierarchy (FR-018)
│       ├── openai_provider.py   # MODIFY: Add structured logging, OTel hooks, raise typed exceptions
│       ├── anthropic_provider.py # MODIFY: Remove `from __future__`, add structured logging, OTel hooks, raise typed exceptions
│       ├── azure_provider.py    # NEW: Azure OpenAI provider with RBAC + API key fallback
│       └── secrets.py           # NEW: SecretBackend protocol + EnvVarBackend default
├── ...

tests/
├── test_llm_providers.py     # NEW: Provider unit tests (OpenAI, Anthropic, Azure)
├── test_llm_registry.py      # NEW: Registry discovery + resolution tests
├── test_llm_secrets.py        # NEW: SecretBackend tests
├── test_llm_errors.py         # NEW: Exception hierarchy + fallback transient-only tests
├── test_observability.py     # NEW: structlog + OTel instrumentation tests
├── ...

pyproject.toml                # MODIFY: Add entry points for openai, anthropic, azure
```

**Structure Decision**: Single project layout. All new code goes into existing `hiveflow/` package structure. New files are `azure_provider.py`, `secrets.py`, `errors.py`, and `observability.py`. New test files for isolated provider/registry/observability/error testing.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `from __future__ import annotations` removal | Constitution 5.1 mandates no PEP 604-style deferred evaluation. Existing LLM code uses it. | Cannot leave it — we're materially modifying these files and must bring them into compliance. |
| `fallback.py` behavior change | FR-019 requires transient-only fallback. Current default is `retry_on=(Exception,)` which catches all errors. | Could add new `TransientFallbackChain` class, but rejected — modifying default is cleaner and the existing `retry_on` parameter still allows override. |
