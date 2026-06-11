#!/usr/bin/env python3
"""Embeddings 03: Compare all three embedding providers.

Runs the same semantic search task across all three providers —
``huggingface`` (default), ``local`` (zero-dep fallback), and
``openai`` (Azure API) — so you can see quality vs speed trade-offs.

The OpenAI provider uses Azure OpenAI with DefaultAzureCredential
(Entra ID RBAC).  If credentials are unavailable, that provider is
simply skipped and the example still runs with the two local providers.

Usage:
    # Local providers only (no API key needed):
    uv run python examples/embeddings/03_provider_comparison.py

    # Include Azure OpenAI:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \\
        uv run python examples/embeddings/03_provider_comparison.py
"""

import asyncio
import os
import time

import numpy as np

from hiveflow.plugins.embeddings import EmbeddingProvider
from hiveflow.plugins.embeddings.huggingface_embeddings import HuggingFaceEmbeddingProvider
from hiveflow.plugins.embeddings.local_embeddings import LocalEmbeddingProvider
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
EMBEDDING_MODEL = "text-embedding-3-small"

# -- Knowledge base --
DOCUMENTS = [
    {"doc_id": "py", "text": "Python is a high-level programming language known for readability and versatility."},
    {"doc_id": "ml", "text": "Machine learning algorithms learn patterns from data to make predictions."},
    {"doc_id": "nn", "text": "Neural networks are computing systems inspired by biological brain structures."},
    {"doc_id": "docker", "text": "Docker containers package applications with their dependencies for deployment."},
    {"doc_id": "k8s", "text": "Kubernetes orchestrates containerized workloads across clusters of machines."},
    {"doc_id": "rest", "text": "REST APIs use HTTP methods to create, read, update, and delete resources."},
    {"doc_id": "quantum", "text": "Quantum computing uses qubits that can exist in superposition states."},
    {"doc_id": "graph", "text": "Graph databases store data as nodes and edges, modeling relationships naturally."},
]

QUERIES = [
    "How do AI systems learn from data?",
    "Container orchestration and deployment",
    "Quantum physics and computing",
]


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n")


async def build_openai_provider() -> EmbeddingProvider | None:
    """Try to build an Azure OpenAI embedding provider. Returns None if unavailable."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", endpoint)

    # Need to create a thin wrapper that routes through AsyncAzureOpenAI
    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    except (ImportError, Exception) as exc:
        print(f"  [!] Azure OpenAI not available: {exc}")
        print("    Install azure-identity: uv sync --extra llm-azure")
        print("    Skipping OpenAI provider.\n")
        return None

    # Create a wrapper that speaks the EmbeddingProvider protocol
    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-06-01",
    )

    class AzureOpenAIEmbeddings(EmbeddingProvider):
        """Thin wrapper over AsyncAzureOpenAI for comparison."""

        @property
        def plugin_id(self) -> str:
            return "openai (Azure)"

        @property
        def description(self) -> str:
            return f"Azure OpenAI {EMBEDDING_MODEL}"

        @property
        def embedding_dimension(self) -> int:
            return 1536

        async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
            resp = await client.embeddings.create(model=model or EMBEDDING_MODEL, input=texts)
            return [item.embedding for item in resp.data]

        def estimate_cost(self, num_tokens: int) -> float:
            return (num_tokens / 1_000_000) * 0.02

    return AzureOpenAIEmbeddings()


async def run_provider(
    provider: EmbeddingProvider,
    texts: list[str],
    queries: list[str],
    documents: list[dict],
) -> None:
    """Run embed + search for one provider and print results."""
    name = provider.plugin_id
    dim = provider.embedding_dimension
    cost = provider.estimate_cost(10_000)

    print(f"  Provider:   {name}")
    print(f"  Dimension:  {dim}")
    print(f"  Cost/10K:   ${cost:.4f}")

    # Embed documents
    t0 = time.perf_counter()
    vectors = await provider.embed(texts)
    embed_time = time.perf_counter() - t0
    print(f"  Embed time: {embed_time:.3f}s ({len(texts)} texts)")

    # Store & search
    store = MemoryVectorStore()
    await store.add(vectors, documents)

    for query in queries:
        t0 = time.perf_counter()
        q_vec = await provider.embed_single(query)
        results = await store.search(q_vec, top_k=3)
        search_time = time.perf_counter() - t0

        print(f"\n  Q: {query!r}  ({search_time*1000:.1f}ms)")
        for rank, (doc, score) in enumerate(results, 1):
            print(f"     {rank}. [{score:.3f}] ({doc['doc_id']}) {doc['text'][:55]}...")

    print()


async def main() -> None:
    texts = [d["text"] for d in DOCUMENTS]

    # -- 1. HuggingFace (default) --
    section("1. HuggingFace -- sentence-transformers (DEFAULT)")
    hf = HuggingFaceEmbeddingProvider()
    await run_provider(hf, texts, QUERIES, DOCUMENTS)

    # -- 2. Local (numpy fallback) --
    section("2. Local -- numpy feature hashing (zero-dep fallback)")
    local = LocalEmbeddingProvider()
    await run_provider(local, texts, QUERIES, DOCUMENTS)

    # -- 3. OpenAI via Azure (optional) --
    section("3. OpenAI via Azure (optional, requires credentials)")
    openai_provider = await build_openai_provider()
    if openai_provider:
        try:
            await run_provider(openai_provider, texts, QUERIES, DOCUMENTS)
        except Exception as e:
            print(f"  [FAIL] Azure OpenAI call failed: {e}")
            print("    Make sure you're on an allowed network and have the right RBAC role.")
    else:
        print("  Skipped (no Azure credentials).\n")

    # -- Summary --
    section("Summary")
    print("  Provider      | Deps              | Quality   | Cost      | Network")
    print("  ------------- | ----------------- | --------- | --------- | --------")
    print("  huggingface   | sentence-trans.   | High      | Free      | First download only")
    print("  local         | numpy (core)      | Adequate  | Free      | None")
    print("  openai        | openai + API key  | Highest   | ~$0.02/1M | Every call")

    print("\n[OK] Done.")


if __name__ == "__main__":
    asyncio.run(main())
