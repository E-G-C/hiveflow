#!/usr/bin/env python3
"""Embeddings 01: Local feature-hashing embeddings (zero-dependency).

Demonstrates the ``local`` embedding provider which uses numpy-only
feature hashing to produce 384-dimensional vectors — no API key, no
model download, no network access.

Good for:
  - Quick prototyping and testing
  - CI/CD environments without GPU or network
  - Scenarios where embedding quality is secondary to speed/cost

Usage:
    uv run python examples/embeddings/01_local_embeddings.py
"""

import asyncio

import numpy as np

from hiveflow.plugins.embeddings.local_embeddings import LocalEmbeddingProvider
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore


# -- Sample knowledge base --
DOCUMENTS = [
    {"doc_id": "py", "text": "Python is a high-level programming language known for readability."},
    {"doc_id": "ml", "text": "Machine learning algorithms learn patterns from data to make predictions."},
    {"doc_id": "nn", "text": "Neural networks are computing systems inspired by biological brain structures."},
    {"doc_id": "docker", "text": "Docker containers package applications with their dependencies."},
    {"doc_id": "k8s", "text": "Kubernetes orchestrates containerized workloads across clusters."},
    {"doc_id": "rest", "text": "REST APIs use HTTP methods to create, read, update, and delete resources."},
    {"doc_id": "quantum", "text": "Quantum computing uses qubits that can exist in superposition states."},
    {"doc_id": "graph", "text": "Graph databases store data as nodes and edges, modeling relationships."},
]


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n")


async def main() -> None:
    provider = LocalEmbeddingProvider()

    # -- 1. Provider info --
    section("1. Provider info")
    print(f"  plugin_id:    {provider.plugin_id}")
    print(f"  dimension:    {provider.embedding_dimension}")
    print(f"  max_batch:    {provider.max_batch_size}")
    print(f"  cost / 10K:   ${provider.estimate_cost(10_000):.4f}")
    print(f"  description:  {provider.description}")

    # -- 2. Generate embeddings --
    section("2. Generate embeddings")
    texts = [d["text"] for d in DOCUMENTS]
    vectors = await provider.embed(texts)
    print(f"  Embedded {len(vectors)} texts -> {len(vectors[0])}-dim vectors")

    # Show norms (should all be ~1.0 since vectors are L2-normalised)
    norms = [np.linalg.norm(v) for v in vectors]
    print(f"  Vector norms:  min={min(norms):.6f}  max={max(norms):.6f}")

    # -- 3. Store & search --
    section("3. Similarity search (MemoryVectorStore)")
    store = MemoryVectorStore()
    await store.add(vectors, DOCUMENTS)
    print(f"  Stored {await store.count()} documents\n")

    queries = [
        "How do AI systems learn from data?",
        "Container orchestration and deployment",
        "Quantum physics and computing",
    ]

    for query in queries:
        q_vec = await provider.embed_single(query)
        results = await store.search(q_vec, top_k=3)
        print(f"  Q: {query!r}")
        for rank, (doc, score) in enumerate(results, 1):
            print(f"     {rank}. [{score:.3f}] ({doc['doc_id']}) {doc['text'][:60]}...")
        print()

    # -- 4. Determinism check --
    section("4. Determinism check")
    v1 = await provider.embed(["test string"])
    v2 = await provider.embed(["test string"])
    print(f"  Same input -> identical output: {v1 == v2}")

    print("\n[OK] Done -- no API key, no model download, no network access needed.")


if __name__ == "__main__":
    asyncio.run(main())
