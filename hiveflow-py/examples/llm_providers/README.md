# LLM Provider Plugin Examples

End-to-end examples for the HiveFlow LLM provider plugin system.

All live examples default to **Azure OpenAI with RBAC** -- no API key required, just `az login`.

## Quick start

```bash
# Install HiveFlow in dev mode
uv sync

# Install Azure extras (for Azure examples)
uv sync --extra llm-azure

# Set the Azure endpoint (RBAC -- no API key needed)
export AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
```

## Examples

| # | File | Credentials | What it covers |
|---|------|-------------|----------------|
| 01 | `01_discovery.py` | None | Provider discovery, capabilities, model resolution, error messages |
| 02 | `02_chat.py` | Azure / OpenAI / Anthropic | Basic chat completions, token usage |
| 03 | `03_streaming.py` | Azure / OpenAI / Anthropic | Real-time token streaming |
| 04 | `04_azure_rbac.py` | Azure | Azure auth modes (RBAC vs API key), endpoint normalization |
| 05 | `05_secret_backend.py` | None | Custom secret backends (dict, vault-style), protocol checks |
| 06 | `06_tier_variables.py` | None | `$SMART_LLM`, `$FAST_LLM`, `$STRATEGIC_LLM` resolution and overrides |
| 07 | `07_fallback_chain.py` | None | FallbackChain, RetryProvider, build\_fallback\_chain with mock providers |
| 08 | `08_observability.py` | Azure / OpenAI / Anthropic | structlog configuration, OTel toggle, live structured log events |
| 09 | `09_multi_turn.py` | Azure / OpenAI / Anthropic | Multi-turn conversation with history, cumulative token tracking |
| 10 | `10_function_calling.py` | Azure / OpenAI | Tool specs, tool_calls parsing, tool result round-trip |
| 11 | `11_json_mode.py` | Azure / OpenAI | Structured JSON output, entity extraction, classification |

## Running

```bash
# No credentials needed (offline):
uv run python examples/llm_providers/01_discovery.py
uv run python examples/llm_providers/05_secret_backend.py
uv run python examples/llm_providers/06_tier_variables.py
uv run python examples/llm_providers/07_fallback_chain.py

# With Azure RBAC (recommended):
AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/02_chat.py

AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/03_streaming.py

AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/04_azure_rbac.py

AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/08_observability.py

AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/09_multi_turn.py

AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/10_function_calling.py

AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/llm_providers/11_json_mode.py
```

## Architecture overview

```
  $SMART_LLM                          SecretBackend
      |                                    |
  HiveFlowConfig.resolve_model()       get_secret("OPENAI_API_KEY")
      |                                    |
  "openai:gpt-4o"                     Provider._get_client()
      |                                    |
  LLMProviderRegistry.resolve_model()  +---+
      |                                |
  (provider, model)                    |
      |                                |
  provider.chat(messages, config) <----+
      |
  structlog event + OTel span/metrics
      |
  LLMResponse
```
