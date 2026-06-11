# Embeddings Examples

Demonstrates the three embedding providers available in HiveFlow.

## Examples

| #   | File                           | Description                                                | API Key?                |
| --- | ------------------------------ | ---------------------------------------------------------- | ----------------------- |
| 01  | `01_local_embeddings.py`       | Zero-dependency feature-hashing provider (numpy only)      | No                      |
| 02  | `02_huggingface_embeddings.py` | Default transformer-based provider (sentence-transformers) | No                      |
| 03  | `03_provider_comparison.py`    | Side-by-side comparison of all three providers             | Optional (Azure OpenAI) |

## Quick Start

```bash
# Run the default (HuggingFace) provider — no API key needed:
uv run python examples/embeddings/02_huggingface_embeddings.py

# Compare all providers (Azure OpenAI optional):
AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/embeddings/03_provider_comparison.py
```

## Providers

| Provider                  | Config value  | Deps                           | Quality                    | Cost             |
| ------------------------- | ------------- | ------------------------------ | -------------------------- | ---------------- |
| **HuggingFace** (default) | `huggingface` | `sentence-transformers` (core) | High (384-dim transformer) | Free, local      |
| **Local**                 | `local`       | `numpy` (core)                 | Adequate (384-dim hashing) | Free, local      |
| **OpenAI**                | `openai`      | `openai` + API key             | Highest (1536-dim)         | ~$0.02/1M tokens |

Set the provider via environment variable:

```bash
HIVEFLOW_EMBEDDING_PROVIDER=huggingface   # default
HIVEFLOW_EMBEDDING_PROVIDER=local         # zero-dep fallback
HIVEFLOW_EMBEDDING_PROVIDER=openai        # requires OPENAI_API_KEY
```
