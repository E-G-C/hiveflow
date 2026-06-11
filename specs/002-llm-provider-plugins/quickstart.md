# Quickstart Validation: LLM Provider Plugins

**Date**: 2026-02-19 | **Plan**: [plan.md](plan.md)

## Prerequisites

- Python 3.11+
- `uv` package manager
- HiveFlow installed in dev mode: `uv sync`
- For Azure RBAC: Azure OpenAI resource with a deployment, identity with "Cognitive Services OpenAI User" role

## QV-1: Provider Discovery

Verify that all built-in providers are auto-discovered.

```bash
uv run python -c "
from hiveflow.plugins.llm import get_llm_registry
registry = get_llm_registry()
ids = registry.list_ids()
print('Discovered providers:', ids)
assert 'openai' in ids, 'openai not discovered'
assert 'anthropic' in ids, 'anthropic not discovered'
print('PASS: OpenAI and Anthropic discovered')
"
```

**Expected**: `Discovered providers: ['anthropic', 'openai']` (or including `'azure'` if `llm-azure` extras installed)

## QV-2: Model Resolution

Verify `provider:model` resolution works.

```bash
uv run python -c "
from hiveflow.plugins.llm import get_llm_registry
registry = get_llm_registry()
provider, model = registry.resolve_model('openai:gpt-4o')
print(f'Provider: {provider.plugin_id}, Model: {model}')
assert provider.plugin_id == 'openai'
assert model == 'gpt-4o'
print('PASS: Model resolution works')
"
```

## QV-3: Azure Provider with API Key

Requires `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` environment variables.

```bash
uv sync --extra llm-azure

uv run python -c "
import asyncio
from hiveflow.plugins.llm import get_llm_registry, LLMConfig, LLMMessage

async def main():
    registry = get_llm_registry()
    provider, model = registry.resolve_model('azure:YOUR-DEPLOYMENT-NAME')

    response = await provider.chat(
        messages=[
            LLMMessage(role='user', content='Say hello in one word.')
        ],
        config=LLMConfig(model=model, max_tokens=10),
    )
    print(f'Response: {response.content}')
    print(f'Model: {response.model}')
    print('PASS: Azure API key auth works')

asyncio.run(main())
"
```

## QV-4: Azure Provider with RBAC

Requires `AZURE_OPENAI_ENDPOINT` and valid Entra ID credentials (service principal env vars, managed identity, or `az login`).

```bash
# Ensure no API key is set (RBAC only)
unset AZURE_OPENAI_API_KEY

uv run python -c "
import asyncio
from hiveflow.plugins.llm import get_llm_registry, LLMConfig, LLMMessage

async def main():
    registry = get_llm_registry()
    provider, model = registry.resolve_model('azure:YOUR-DEPLOYMENT-NAME')

    response = await provider.chat(
        messages=[
            LLMMessage(role='user', content='Say hello in one word.')
        ],
        config=LLMConfig(model=model, max_tokens=10),
    )
    print(f'Response: {response.content}')
    print('PASS: Azure RBAC auth works')

asyncio.run(main())
"
```

## QV-5: Tier Variable Resolution

Verify that `$SMART_LLM` resolves correctly through the config system.

```bash
uv run python -c "
from hiveflow.core.config import get_config
from hiveflow.plugins.llm import get_llm_registry

config = get_config()
model_ref = config.resolve_model('\$SMART_LLM')
print(f'Tier resolved to: {model_ref}')

registry = get_llm_registry()
provider, model = registry.resolve_model(model_ref)
print(f'Provider: {provider.plugin_id}, Model: {model}')
print('PASS: Tier variable resolution works')
"
```

**Expected**: `Tier resolved to: openai:gpt-4o` (default)

## QV-6: Missing Provider Error

Verify clear error message for uninstalled providers.

```bash
uv run python -c "
from hiveflow.plugins.llm import get_llm_registry
registry = get_llm_registry()
try:
    registry.resolve_model('google:gemini-2.0-flash')
except KeyError as e:
    print(f'Error: {e}')
    print('PASS: Clear error for missing provider')
"
```

**Expected**: Error message includes available providers and (ideally) install suggestion.

## QV-7: Full Test Suite

```bash
uv run pytest tests/ -v --tb=short -q
```

**Expected**: All tests pass, including new provider and registry tests.

## QV-8: Structured Logging Output

Verify that provider calls emit structured log events via `structlog`.

```bash
uv run python -c "
import asyncio, logging
from hiveflow.core.observability import configure_logging

configure_logging()

from hiveflow.plugins.llm import get_llm_registry, LLMConfig, LLMMessage

async def main():
    registry = get_llm_registry()
    ids = registry.list_ids()
    if 'openai' not in ids:
        print('SKIP: openai provider not available')
        return
    provider, model = registry.resolve_model('openai:gpt-4o-mini')
    response = await provider.chat(
        messages=[LLMMessage(role='user', content='Say hi.')],
        config=LLMConfig(model=model, max_tokens=10),
    )
    print(f'Response: {response.content}')
    print('PASS: Structured log event emitted (check console output above)')

asyncio.run(main())
"
```

**Expected**: Console shows a structured log line containing `llm.chat.complete`, `provider_id=openai`, `model=gpt-4o-mini`, `latency_ms=...`, `prompt_tokens=...`.

## QV-9: OTel Toggle (no-op when disabled)

Verify that OTel instrumentation is no-op when the toggle is off (default).

```bash
uv run python -c "
from hiveflow.core.observability import tracer, meter, llm_duration, llm_token_usage
import os

otel_enabled = os.environ.get('HIVEFLOW_OTEL_ENABLED', 'false')
print(f'HIVEFLOW_OTEL_ENABLED={otel_enabled}')

if otel_enabled.lower() != 'true':
    # When disabled, metrics should be None (no overhead)
    assert llm_duration is None, 'llm_duration should be None when OTel disabled'
    assert llm_token_usage is None, 'llm_token_usage should be None when OTel disabled'
    print('PASS: OTel metrics are None when disabled')
else:
    print('OTel is enabled — metrics are active')
    print('PASS: OTel metrics created')
"
```

**Expected**: With default settings, OTel metrics are `None` (no overhead). When `HIVEFLOW_OTEL_ENABLED=true`, metrics are created.

## QV-10: SecretBackend Pluggability

Verify that the secret backend can be swapped.

```bash
uv run python -c "
from hiveflow.plugins.llm.secrets import get_secret_backend, set_secret_backend, EnvVarBackend
import os

# Default backend reads from env vars
backend = get_secret_backend()
assert isinstance(backend, EnvVarBackend), 'Default should be EnvVarBackend'

# Set a test value and verify resolution
os.environ['TEST_SECRET_KEY'] = 'test-value-123'
assert backend.get_secret('TEST_SECRET_KEY') == 'test-value-123'

# Swap to a custom backend
class DictBackend:
    def __init__(self, secrets: dict):
        self._secrets = secrets
    def get_secret(self, key: str) -> str | None:
        return self._secrets.get(key)

set_secret_backend(DictBackend({'MY_KEY': 'custom-value'}))
assert get_secret_backend().get_secret('MY_KEY') == 'custom-value'
assert get_secret_backend().get_secret('MISSING') is None

# Restore default
set_secret_backend(EnvVarBackend())
print('PASS: SecretBackend is pluggable')

del os.environ['TEST_SECRET_KEY']
"
```

**Expected**: `PASS: SecretBackend is pluggable`

## QV-11: Typed Exception Hierarchy

Verify that provider errors use typed exceptions.

```bash
uv run python -c "
from hiveflow.plugins.llm.errors import (
    LLMProviderError,
    LLMAuthError,
    LLMRateLimitError,
    LLMModelNotFoundError,
    LLMConnectionError,
)

# Verify hierarchy
assert issubclass(LLMAuthError, LLMProviderError)
assert issubclass(LLMRateLimitError, LLMProviderError)
assert issubclass(LLMModelNotFoundError, LLMProviderError)
assert issubclass(LLMConnectionError, LLMProviderError)

# Verify provider_id attribute
err = LLMAuthError('Invalid API key', provider_id='openai')
assert err.provider_id == 'openai'
assert 'Invalid API key' in str(err)

print('PASS: Typed exception hierarchy works')
"
```

## QV-12: FallbackChain Transient-Only Default

Verify that FallbackChain only cascades on transient errors.

```bash
uv run python -c "
import asyncio
from unittest.mock import AsyncMock
from hiveflow.plugins.llm import LLMConfig, LLMMessage
from hiveflow.plugins.llm.errors import LLMAuthError, LLMConnectionError
from hiveflow.core.fallback import FallbackChain

async def main():
    # Create mock providers
    failing_provider = AsyncMock()
    failing_provider.plugin_id = 'failing'
    fallback_provider = AsyncMock()
    fallback_provider.plugin_id = 'fallback'

    chain = FallbackChain([
        (failing_provider, 'model-a'),
        (fallback_provider, 'model-b'),
    ])

    # Test: Auth error should NOT cascade (fails immediately)
    failing_provider.chat.side_effect = LLMAuthError('bad key', provider_id='failing')
    try:
        await chain.chat([], LLMConfig(model='test'))
        assert False, 'Should have raised'
    except LLMAuthError:
        assert fallback_provider.chat.call_count == 0, 'Should not have tried fallback'
        print('PASS: Auth error fails immediately (no cascade)')

    # Reset
    fallback_provider.chat.reset_mock()

    # Test: Connection error SHOULD cascade
    failing_provider.chat.side_effect = LLMConnectionError('timeout', provider_id='failing')
    fallback_provider.chat.return_value = AsyncMock(content='ok', model='m', usage=None, tool_calls=None, finish_reason='stop')
    response = await chain.chat([], LLMConfig(model='test'))
    assert fallback_provider.chat.call_count == 1, 'Should have cascaded to fallback'
    print('PASS: Connection error cascades to fallback')

asyncio.run(main())
"
```

**Expected**: Both "PASS" messages printed — auth errors fail immediately, connection errors cascade.
