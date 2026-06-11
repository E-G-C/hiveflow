# Resilience Examples

Examples demonstrating HiveFlow's production resilience features — fallback
chains, retry providers, circuit breakers, and cost tracking.

## Examples

| # | Script | What it shows | API Key? |
|---|--------|---------------|:--------:|
| 01 | `01_fallback_and_cost.py` | Fallback chains, retry providers, cost tracking | No |

## Running

```bash
uv run python examples/resilience/01_fallback_and_cost.py
```

## Key Concepts

- **FallbackChain** — cascade through LLM providers on failure
- **RetryProvider** — retry a single provider N times
- **CostTracker** — monitor token usage and estimated costs
- **ResilientLLMProvider** — all-in-one wrapper (auto-applied to agents)
