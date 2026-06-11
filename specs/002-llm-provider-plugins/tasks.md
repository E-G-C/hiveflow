# Tasks: LLM Provider Plugin Architecture

**Input**: Design documents from `/specs/002-llm-provider-plugins/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included — the feature spec explicitly requires "Tests for all new providers and the discovery mechanism" (Scope Boundaries).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `hiveflow/` package at repository root, `tests/` at repository root
- Entry points and dependencies in `pyproject.toml`

---

## Phase 1: Setup (Constitution Compliance & Dependency Config)

**Purpose**: Fix constitution violations and prepare project configuration for all subsequent work.

- [x] T001 <!-- bd:hiveflow-4mg.1 --> Remove `from __future__ import annotations` from `hiveflow/plugins/llm/__init__.py`, `hiveflow/plugins/llm/anthropic_provider.py`, `hiveflow/core/registry.py`, and `hiveflow/core/config.py` per constitution 5.1 (R10). Verify no runtime type errors after removal — all files already use Python 3.11+ native `X | Y` union syntax
- [x] T002 <!-- bd:hiveflow-4mg.2 --> [P] Update `pyproject.toml`: (a) add `opentelemetry-api>=1.27.0` to a new `observability` optional-dependency group, (b) register entry points under `[project.entry-points."hiveflow.llm"]` for `openai = "hiveflow.plugins.llm.openai_provider:OpenAIProvider"`, `anthropic = "hiveflow.plugins.llm.anthropic_provider:AnthropicProvider"`, and `azure = "hiveflow.plugins.llm.azure_provider:AzureOpenAIProvider"`. Run `uv sync` to activate entry points

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure modules that ALL provider stories depend on. SecretBackend enables pluggable credentials; observability module enables structured logging and OTel instrumentation; error hierarchy enables typed exception handling; registry enhancements enable improved error messages and `provider_id` canonicalization.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 <!-- bd:hiveflow-4mg.3 --> [P] Create `hiveflow/plugins/llm/secrets.py` implementing the `SecretBackend` Protocol (runtime_checkable), `EnvVarBackend` class (reads `os.environ`), `get_secret_backend()` and `set_secret_backend()` global accessors per data-model.md SecretBackend section and R8. No `from __future__ import annotations`
- [x] T004 <!-- bd:hiveflow-4mg.4 --> [P] Create `hiveflow/core/observability.py` with: (a) `configure_logging()` function setting up structlog with ConsoleRenderer (dev) or JSONRenderer (production) based on `HIVEFLOW_ENV` env var, bridging stdlib via `ProcessorFormatter` per R6; (b) OTel instrumentation: `tracer`, `meter`, `llm_duration` histogram, `llm_token_usage` counter — all `None` when `HIVEFLOW_OTEL_ENABLED` is not `"true"` or `opentelemetry` not installed, per R7. No `from __future__ import annotations`
- [x] T017 <!-- bd:hiveflow-4mg.17 --> [P] Create `hiveflow/plugins/llm/errors.py` implementing the typed exception hierarchy per FR-018 and R11: `LLMProviderError(Exception)` base class with `message: str` and `provider_id: str | None` attributes, plus subclasses `LLMAuthError`, `LLMRateLimitError`, `LLMModelNotFoundError`, `LLMConnectionError` — all inheriting from `LLMProviderError` with no additional logic. Export all from `hiveflow/plugins/llm/__init__.py`. No `from __future__ import annotations`
- [x] T018 <!-- bd:hiveflow-4mg.18 --> Update `hiveflow/core/fallback.py`: (a) import `LLMRateLimitError` and `LLMConnectionError` from `hiveflow.plugins.llm.errors`, (b) change `FallbackChain.__init__` default `retry_on` from `(Exception,)` to `(LLMRateLimitError, LLMConnectionError)` per FR-019 and R12, (c) change `RetryProvider.__init__` default `retry_on` from `(Exception,)` to `(LLMRateLimitError, LLMConnectionError)`, (d) update `build_fallback_chain()` accordingly. Preserve the `retry_on` parameter for caller override. **⚠️ Breaking change**: callers relying on the `(Exception,)` default will see different behavior — document in CHANGELOG.md
- [x] T005 <!-- bd:hiveflow-4mg.5 --> Update `hiveflow/plugins/llm/__init__.py`: (a) add `provider_id` convenience property to `LLMProvider` that delegates to `plugin_id`, (b) enhance `resolve_model()` error messages — `ValueError` for invalid format with example, `KeyError` for unknown provider with available list and suggested install command `uv add hiveflow[llm-{name}]` per sdk-api.md error contract and FR-008/FR-009, (c) re-export `SecretBackend`, `EnvVarBackend`, `get_secret_backend`, `set_secret_backend` from secrets module

**Checkpoint**: Foundation ready — SecretBackend, observability, error hierarchy, transient-only fallback, and improved registry available for provider updates.

---

## Phase 3: User Story 2 — Provider Plugin Discovery and Registration (Priority: P2) 🎯 MVP

**Goal**: All built-in LLM providers (OpenAI, Anthropic) are auto-discovered via entry points, `provider:model` resolution works correctly, providers raise typed exceptions, and clear error messages guide users when providers are missing.

**Independent Test**: Call `get_llm_registry()`, verify `openai` and `anthropic` appear in `list_ids()`, confirm `resolve_model("openai:gpt-4o")` returns the correct provider instance and model string. Verify that SDK errors are mapped to typed exceptions.

**Why first**: The spec states "every other provider story depends on the discovery mechanism working correctly." US1 (Azure) and US3 (mixed providers) cannot function without entry-point-based discovery.

### Implementation for User Story 2

- [x] T006 <!-- bd:hiveflow-4mg.6 --> [P] [US2] Update `hiveflow/plugins/llm/openai_provider.py`: replace `os.environ.get("OPENAI_API_KEY")` with `get_secret_backend().get_secret("OPENAI_API_KEY")` in `_get_client()`, add `structlog.get_logger()` and emit `llm.chat.complete` / `llm.chat.error` structured events with `provider_id`, `model`, `latency_ms`, `prompt_tokens`, `completion_tokens` in `chat()` and `chat_stream()`, add OTel span (`chat openai`) and metric recording when `tracer`/`llm_duration`/`llm_token_usage` are not None per R6/R7 and sdk-api.md Observability contract
- [x] T007 <!-- bd:hiveflow-4mg.7 --> [P] [US2] Update `hiveflow/plugins/llm/anthropic_provider.py`: same SecretBackend + structlog + OTel instrumentation as T006 but for `ANTHROPIC_API_KEY` and `provider_id="anthropic"`. `from __future__` already removed in T001
- [x] T019 <!-- bd:hiveflow-4mg.19 --> [P] [US2] Update `hiveflow/plugins/llm/openai_provider.py`: wrap SDK calls in `chat()` and `chat_stream()` with try/except blocks that map OpenAI SDK exceptions to typed exceptions per FR-018, FR-023, and R11 exception mapping table: `openai.AuthenticationError` → `LLMAuthError`, `openai.RateLimitError` → `LLMRateLimitError`, `openai.NotFoundError` → `LLMModelNotFoundError`, `openai.APIConnectionError`/`openai.APITimeoutError`/`openai.InternalServerError` → `LLMConnectionError`. In `chat_stream()`, catch errors mid-stream and raise `LLMConnectionError` — partial content is discarded per FR-023 and R14. Include `provider_id=self.plugin_id` in all exceptions
- [x] T020 <!-- bd:hiveflow-4mg.20 --> [P] [US2] Update `hiveflow/plugins/llm/anthropic_provider.py`: same typed exception mapping as T019 but for Anthropic SDK exceptions per R11 mapping table: `anthropic.AuthenticationError` → `LLMAuthError`, `anthropic.RateLimitError` → `LLMRateLimitError`, `anthropic.NotFoundError` → `LLMModelNotFoundError`, `anthropic.APIConnectionError`/`anthropic.APITimeoutError` → `LLMConnectionError`. In `chat_stream()`, discard partial content on error per FR-023. Include `provider_id=self.plugin_id` in all exceptions
- [x] T008 <!-- bd:hiveflow-4mg.8 --> [US2] Write tests in `tests/test_llm_registry.py`: (a) test `get_llm_registry()` returns singleton, (b) test `list_ids()` includes `"openai"` and `"anthropic"` after discovery, (c) test `resolve_model("openai:gpt-4o")` returns `(OpenAIProvider, "gpt-4o")`, (d) test `resolve_model("gpt-4o")` raises `ValueError` with format hint, (e) test `resolve_model("google:gemini")` raises `KeyError` with available list and install suggestion, (f) test graceful skip when entry point import fails (FR-014)
- [x] T009 <!-- bd:hiveflow-4mg.9 --> [P] [US2] Write tests in `tests/test_llm_secrets.py`: (a) test `EnvVarBackend.get_secret()` reads from `os.environ`, (b) test `get_secret_backend()` returns `EnvVarBackend` by default, (c) test `set_secret_backend()` swaps the active backend, (d) test custom backend (dict-based) works, (e) test `SecretBackend` is `runtime_checkable` and `isinstance()` works
- [x] T010 <!-- bd:hiveflow-4mg.10 --> [P] [US2] Write tests in `tests/test_observability.py`: (a) test `configure_logging()` sets up structlog without errors, (b) test `tracer`/`meter`/`llm_duration`/`llm_token_usage` are `None` when `HIVEFLOW_OTEL_ENABLED` is not set, (c) test `_otel_enabled` flag reads from env var correctly, (d) test structlog logger emits expected event structure
- [x] T021 <!-- bd:hiveflow-4mg.21 --> [P] [US2] Write tests in `tests/test_llm_errors.py`: (a) test `LLMProviderError` hierarchy — all subclasses inherit from `LLMProviderError`, `isinstance()` checks work, (b) test `provider_id` attribute is carried on all exception subclasses, (c) test `LLMAuthError("bad key", provider_id="openai")` preserves message and provider_id, (d) test OpenAI provider maps `openai.AuthenticationError` → `LLMAuthError`, `openai.RateLimitError` → `LLMRateLimitError` (mock SDK), (e) test Anthropic provider maps `anthropic.AuthenticationError` → `LLMAuthError` (mock SDK), (f) test `chat_stream()` mid-stream error raises `LLMConnectionError` and discards partial content (mock SDK stream that errors after 2 chunks), (g) test `FallbackChain` cascades on `LLMConnectionError` but fails immediately on `LLMAuthError` per FR-019, (h) test `FallbackChain` cascades on `LLMRateLimitError`, (i) test `FallbackChain` with `retry_on=(Exception,)` override cascades on all errors

**Checkpoint**: At this point, `openai` and `anthropic` providers are auto-discovered via entry points, `resolve_model()` works with clear errors, all providers use SecretBackend, emit structured logs, and raise typed exceptions. Fallback chain respects transient-only cascading. US2 acceptance scenarios 1, 3, 4 verified.

---

## Phase 4: User Story 1 — Azure OpenAI with RBAC Authentication (Priority: P1, depends on US2)

**Goal**: Enterprise teams can authenticate to Azure OpenAI using Microsoft Entra ID RBAC (DefaultAzureCredential) with automatic token refresh, or fall back to API key auth. Clear error messages guide users through configuration. All errors are typed exceptions.

**Independent Test**: Set `AZURE_OPENAI_ENDPOINT` + service-principal env vars (or `AZURE_OPENAI_API_KEY`), call `resolve_model("azure:deployment-name")`, execute `provider.chat()`, verify successful response. Also test with no credentials to verify `LLMAuthError` message quality.

### Implementation for User Story 1

- [x] T011 <!-- bd:hiveflow-4mg.11 --> [US1] Create `hiveflow/plugins/llm/azure_provider.py` implementing `AzureOpenAIProvider(LLMProvider)` with: (a) `plugin_id = "azure"`, all capability flags `True` per data-model.md, (b) lazy `_get_client()` with auth decision tree: check `AZURE_OPENAI_API_KEY` via SecretBackend first → API key auth, else try RBAC via `DefaultAzureCredential` + `get_bearer_token_provider("https://cognitiveservices.azure.com/.default")` → `AsyncAzureOpenAI(azure_ad_token_provider=...)`, (c) `azure-identity` imported lazily inside `_get_client()` with actionable `ImportError` referencing `uv add hiveflow[llm-azure]`, (d) RBAC failure error message referencing "Cognitive Services OpenAI User" role per FR-006, (e) `chat()` and `chat_stream()` reusing OpenAI message format (same API surface as `AsyncOpenAI`), (f) structlog events and OTel instrumentation matching T006/T007 pattern, (g) `api_version` defaulting to `"2024-10-21"` with `OPENAI_API_VERSION` override via SecretBackend. Reference R1, R2, R4 for implementation patterns
- [x] T022 <!-- bd:hiveflow-4mg.22 --> [US1] Update `hiveflow/plugins/llm/azure_provider.py`: (a) wrap SDK calls in `chat()` and `chat_stream()` with typed exception mapping per FR-018/FR-023 — `openai.AuthenticationError` → `LLMAuthError`, `openai.RateLimitError` → `LLMRateLimitError`, `openai.NotFoundError` → `LLMModelNotFoundError`, `openai.APIConnectionError`/`openai.APITimeoutError`/`openai.InternalServerError` → `LLMConnectionError`, (b) raise `LLMAuthError` (not generic Exception) when no credentials are configured — include "Cognitive Services OpenAI User" in the message per FR-006, (c) raise `LLMAuthError` when `azure-identity` is not installed (lazy import failure, FR-020), (d) `chat_stream()` discards partial content on mid-stream error per FR-023/R14, (e) use `DefaultAzureCredential` without customization per FR-021/R1. Include `provider_id="azure"` in all exceptions
- [x] T012 <!-- bd:hiveflow-4mg.12 --> [US1] Write tests in `tests/test_llm_providers.py`: (a) test `AzureOpenAIProvider.plugin_id == "azure"` and all capability flags, (b) test RBAC auth path — mock `DefaultAzureCredential` and `get_bearer_token_provider`, verify `AsyncAzureOpenAI` created with `azure_ad_token_provider`, (c) test API key fallback — set `AZURE_OPENAI_API_KEY` in env, verify `AsyncAzureOpenAI` created with `api_key`, (d) test no-credentials error message contains "Cognitive Services OpenAI User" and both auth options, (e) test missing `azure-identity` raises `ImportError` with install command, (f) test `chat()` returns `LLMResponse` with correct fields (mock SDK), (g) test `chat_stream()` yields tokens (mock SDK), (h) test structlog event emission during chat
- [x] T023 <!-- bd:hiveflow-4mg.23 --> [US1] Update tests in `tests/test_llm_providers.py`: (a) test no-credentials error raises `LLMAuthError` (not generic Exception) with `provider_id="azure"`, (b) test missing `azure-identity` raises `LLMAuthError` (not `ImportError`) with install command and `provider_id="azure"` per FR-020, (c) test `chat()` SDK auth error raises `LLMAuthError`, (d) test `chat()` SDK rate limit raises `LLMRateLimitError`, (e) test `chat_stream()` mid-stream connection error raises `LLMConnectionError` and partial content is lost (mock stream errors after 2 chunks)

**Checkpoint**: At this point, Azure provider is fully functional with RBAC + API key auth, all errors are typed exceptions. US1 acceptance scenarios 1-5 verified. US2 scenario 2 (azure in registry) also verified.

---

## Phase 5: User Story 3 — Mixed Cloud and Local Providers in One Workflow (Priority: P3)

**Goal**: Teams can assign different providers to different agents in one workflow, use tier variables (`$SMART_LLM`, `$FAST_LLM`) that resolve to `provider:model` strings, and rely on fallback chains that cascade only on transient errors.

**Independent Test**: Define a mock two-agent workflow where one agent uses `openai:gpt-4o` and another uses `azure:deployment`, verify both resolve to different provider instances. Verify FallbackChain only cascades on transient errors. Verify `$SMART_LLM` resolves through config to a valid `provider:model` and then to a provider instance.

### Implementation for User Story 3

- [x] T013 <!-- bd:hiveflow-4mg.13 --> [P] [US3] Write integration tests in `tests/test_llm_integration.py` for multi-provider model assignment: (a) test resolving two different provider:model strings returns different provider instances, (b) test FallbackChain with two providers — first fails, second succeeds, (c) test FallbackChain retry behavior (max_retries_per_provider), (d) test per-agent model resolution scenario — multiple agents each get their own provider via `resolve_model()`
- [x] T014 <!-- bd:hiveflow-4mg.14 --> [P] [US3] Write integration tests in `tests/test_llm_integration.py` for tier variable resolution: (a) test `HiveFlowConfig.resolve_model("$SMART_LLM")` returns `"openai:gpt-4o"` (default), (b) test `resolve_model("$FAST_LLM")` → `"openai:gpt-4o-mini"`, (c) test tier variable → registry.resolve_model() → (provider, model) end-to-end chain, (d) test custom tier override via env var
- [x] T024 <!-- bd:hiveflow-4mg.24 --> [P] [US3] Write integration tests in `tests/test_llm_integration.py` for transient-only fallback behavior: (a) test FallbackChain with `LLMAuthError` on first provider — fails immediately without trying second provider, (b) test FallbackChain with `LLMModelNotFoundError` on first provider — fails immediately, (c) test FallbackChain with `LLMConnectionError` on first provider — cascades to second provider and succeeds, (d) test FallbackChain with `LLMRateLimitError` on first provider — cascades to second provider, (e) test `build_fallback_chain()` uses transient-only default, (f) test `RetryProvider` only retries on transient errors by default

**Checkpoint**: All user stories independently functional. Multi-provider workflows, tier variables, and transient-only fallback chains verified end-to-end.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, regression testing, capability mismatch utility, and quickstart verification across all stories.

- [x] T025 <!-- bd:hiveflow-4mg.25 --> Add capability mismatch warning utility to `hiveflow/plugins/llm/__init__.py` per FR-022 and R13: create a `check_provider_capabilities(provider: LLMProvider, required: list[str]) -> list[str]` function that checks a provider's capability flags against a list of required capabilities (e.g., `["function_calling", "vision"]`), logs a structured `structlog` warning for each missing capability naming the provider and the capability, and returns the list of missing capabilities. This utility is called by the agent/workflow layer when assigning a provider to an agent — the actual prompt-based workaround integration is in the agents-and-teams feature
- [x] T015 <!-- bd:hiveflow-4mg.15 --> Run full test suite with `cd src; pytest` (or `uv run pytest tests/ -v --tb=short`) and fix any regressions. Verify SC-005: all existing tests (409+) continue to pass alongside new tests
- [x] T026 <!-- bd:hiveflow-4mg.26 --> Run full test suite including new error/fallback tests. Verify SC-005: all existing tests plus new tests (T021, T023, T024) pass. **Note**: T013's FallbackChain tests used the old `(Exception,)` default — verify they still pass after T018's default change; update mock exception types to `LLMConnectionError` if needed. Fix any regressions
- [x] T016 <!-- bd:hiveflow-4mg.16 --> [P] Run quickstart validations QV-1 through QV-10 from `specs/002-llm-provider-plugins/quickstart.md`. Verify each produces expected output. Fix any failures discovered
- [x] T027 <!-- bd:hiveflow-4mg.27 --> [P] Run quickstart validations QV-11 (exception hierarchy) and QV-12 (fallback transient-only) from `specs/002-llm-provider-plugins/quickstart.md`. Verify each produces expected output. Fix any failures discovered

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001 must complete before T005 modifies `__init__.py`; T002 must complete for entry points to be discoverable). T017 and T018 are new foundational tasks with no prior dependencies beyond T001
- **US2 (Phase 3)**: Depends on Foundational — providers need SecretBackend (T003), observability (T004), and error hierarchy (T017) before instrumentation. T019/T020 depend on T017 (imports errors)
- **US1 (Phase 4)**: Depends on US2 — Azure provider uses the same patterns established in T006/T007 and requires entry point discovery (T002) to be registered. T022 depends on T017 (imports errors)
- **US3 (Phase 5)**: Depends on US1 and US2 — integration tests exercise Azure, OpenAI, and Anthropic providers together. T024 depends on T018 (fallback default change)
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1 (Setup) ──→ Phase 2 (Foundational) ──→ Phase 3 (US2: Discovery)
                    [+T017 errors, T018 fallback]   [+T019/T020 typed exc, T021 tests]
                                                        │
                                                        ├──→ Phase 4 (US1: Azure)
                                                        │    [+T022 typed exc, T023 tests]
                                                        │           │
                                                        │           ├──→ Phase 5 (US3: Mixed)
                                                        │           │    [+T024 fallback tests]
                                                        │           │           │
                                                        └───────────┴───────────┴──→ Phase 6 (Polish)
                                                                                    [T025 capability, T026/T027 validation]
```

- **US2 (P2)**: Executed first despite P2 priority — spec states "every other provider story depends on the discovery mechanism"
- **US1 (P1)**: Depends on US2 — Azure provider is registered and discovered via the entry point system that US2 establishes
- **US3 (P3)**: Depends on US1 + US2 — integration tests verify multi-provider scenarios including Azure

### Within Each User Story

- Tests and implementation tasks marked [P] can run in parallel (different files)
- Registry/init changes (T005, T008) should complete before provider-specific tests rely on them
- Each provider update (T006, T007, T019, T020) is independent — different files, no shared state
- T017 and T018 are independent new/modified files — parallel within Phase 2

### Parallel Opportunities

**Phase 1**: T001 and T002 touch different files — can run in parallel
**Phase 2**: T003, T004, T017 are independent new files — fully parallel. T018 depends on T017 (imports errors module). T005 depends on T003 and T017 (imports secrets and errors)
**Phase 3**: T019 and T020 are independent files — parallel. T021 depends on T019/T020 (tests exercise typed exceptions). T008, T009, T010 are independent test files — parallel
**Phase 4**: T022 then T023 (sequential — tests require implementation)
**Phase 5**: T024 depends on T018 (fallback default) and T019/T020 (typed exceptions from providers)
**Phase 6**: T025, T026, T027 can be largely parallel

---

## Parallel Example: Phase 2 (Foundational) — New Tasks

```bash
# Three foundational modules can be built in parallel (different files):
Task: "T003 [P] Create secrets.py — SecretBackend Protocol"
Task: "T004 [P] Create observability.py — structlog + OTel"
Task: "T017 [P] Create errors.py — LLMProviderError hierarchy"

# Then T018 (depends on T017 for imports):
Task: "T018 Update fallback.py — transient-only default"
```

## Parallel Example: Phase 3 (US2) — Typed Exception Updates

```bash
# Provider exception mapping can be done in parallel (different files):
Task: "T019 [P] [US2] Update openai_provider.py with typed exception mapping"
Task: "T020 [P] [US2] Update anthropic_provider.py with typed exception mapping"

# Then error tests after both complete:
Task: "T021 [P] [US2] Write exception + fallback tests in tests/test_llm_errors.py"
```

---

## Implementation Strategy

### MVP First (US2 Only)

1. Complete Phase 1: Setup (constitution fix + pyproject.toml)
2. Complete Phase 2: Foundational (SecretBackend + observability + error hierarchy + fallback update + registry enhancements)
3. Complete Phase 3: US2 (provider updates with SecretBackend, observability, typed exceptions + tests)
4. **STOP and VALIDATE**: Run `pytest` — OpenAI and Anthropic auto-discovered, resolve_model works, structured logs emitting, typed exceptions raised, transient-only fallback working
5. Deliver: Framework has working entry-point discovery for existing providers with full error taxonomy

### Incremental Delivery

1. Setup + Foundational → Infrastructure ready (including error hierarchy + fallback change)
2. Add US2 → Discovery works, existing providers instrumented with typed exceptions → **MVP!**
3. Add US1 → Azure RBAC provider available with typed exceptions → Enterprise-ready
4. Add US3 → Multi-provider integration + transient fallback verified → Full feature complete
5. Polish → Capability mismatch utility + all QV validations pass → Ship-ready

### FR-to-Task Traceability

| FR | Task(s) | Phase |
|----|---------|-------|
| FR-001 (entry points) | T002 | Setup |
| FR-002 (Azure RBAC) | T011 | US1 |
| FR-003 (API key fallback) | T011 | US1 |
| FR-004 (Azure token provider) | T011 | US1 |
| FR-005 (Azure capabilities) | T011, T012 | US1 |
| FR-006 (RBAC error messages) | T011, T022, T023 | US1 |
| FR-007 (azure-identity dep) | T002 | Setup |
| FR-008 (resolve_model) | T005 | Foundational |
| FR-009 (missing provider error) | T005, T008 | Foundational, US2 |
| FR-010 (per-agent assignment) | T013 | US3 |
| FR-011 (tier variables) | T014 | US3 |
| FR-012 (provider guideline) | — | Already complete (provider-dev.md) |
| FR-013 (capability flags) | T011, T012 | US1 |
| FR-014 (graceful discovery) | T008 | US2 |
| FR-015 (structlog) | T004, T006, T007, T011 | Foundational, US2, US1 |
| FR-016 (OTel) | T004, T006, T007, T011 | Foundational, US2, US1 |
| FR-017 (SecretBackend) | T003, T006, T007, T011, T009 | Foundational, US2, US1 |
| FR-018 (typed exceptions) | T017, T019, T020, T022, T021, T023 | Foundational, US2, US1 |
| FR-019 (transient fallback) | T018, T021, T024 | Foundational, US2, US3 |
| FR-020 (lazy init failure) | T022, T023 | US1 |
| FR-021 (Azure DefaultAzureCredential) | T011, T022 | US1 |
| FR-022 (capability mismatch) | T025 | Polish |
| FR-023 (streaming errors) | T019, T020, T022, T021, T023 | US2, US1 |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- US2 is implemented before US1 despite lower priority because the spec identifies it as foundational
- All new files must NOT use `from __future__ import annotations` (constitution 5.1)
- Run `uv sync` after T002 to activate entry points before testing discovery
- Tasks T001–T016 were generated in the 2026-02-19 session; tasks T017–T027 were added in the 2026-02-25 session to cover FR-018 through FR-023 (typed exceptions, transient-only fallback, streaming errors, capability mismatch)
