#!/usr/bin/env python3
"""Embeddings 02: HuggingFace transformer embeddings (default provider).

Demonstrates the ``huggingface`` embedding provider — the default in
HiveFlow. Uses the ``sentence-transformers`` library (core dependency)
to run ``all-MiniLM-L6-v2`` locally.

Features:
  - High-quality 384-dim embeddings
  - First run downloads the model (~80 MB, cached in ~/.cache/huggingface/)
  - Subsequent runs use the cached model — no network needed
  - Free, no API key

Usage:
    uv run python examples/embeddings/02_huggingface_embeddings.py
"""

import asyncio
import time

import numpy as np

from hiveflow.plugins.embeddings.huggingface_embeddings import HuggingFaceEmbeddingProvider
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore


# -- Sample knowledge base --
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


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n")


async def main() -> None:
    provider = HuggingFaceEmbeddingProvider()

    # -- 1. Provider info --
    section("1. Provider info")
    print(f"  plugin_id:    {provider.plugin_id}")
    print(f"  dimension:    {provider.embedding_dimension}")
    print(f"  max_batch:    {provider.max_batch_size}")
    print(f"  cost / 10K:   ${provider.estimate_cost(10_000):.4f}  (free!)")
    print(f"  description:  {provider.description}")

    # -- 2. Generate embeddings (first call loads the model) --
    section("2. Generate embeddings")
    texts = [d["text"] for d in DOCUMENTS]

    t0 = time.perf_counter()
    vectors = await provider.embed(texts)
    elapsed = time.perf_counter() - t0

    print(f"  Embedded {len(vectors)} texts -> {len(vectors[0])}-dim vectors")
    print(f"  Time: {elapsed:.2f}s (includes model load on first run)")

    norms = [float(np.linalg.norm(v)) for v in vectors]
    print(f"  Vector norms:  min={min(norms):.6f}  max={max(norms):.6f}")

    # -- 3. Pairwise similarity matrix --
    section("3. Pairwise similarity (dot product of normalised vectors)")
    mat = np.array(vectors)
    sim = mat @ mat.T
    labels = [d["doc_id"] for d in DOCUMENTS]

    # Print header
    header = "        " + "  ".join(f"{l:>6}" for l in labels)
    print(header)
    for i, label in enumerate(labels):
        row = "  ".join(f"{sim[i][j]:6.3f}" for j in range(len(labels)))
        print(f"  {label:>5}  {row}")
    print()

    # -- 4. Semantic search --
    section("4. Semantic search (MemoryVectorStore)")
    store = MemoryVectorStore()
    await store.add(vectors, DOCUMENTS)

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

    # -- 5. Custom model --
    section("5. Using a different model")
    print("  You can pass any sentence-transformers model name:")
    print("    await provider.embed(texts, model='all-mpnet-base-v2')")
    print("    await provider.embed(texts, model='paraphrase-multilingual-MiniLM-L12-v2')")
    print("  The model is downloaded once and cached in ~/.cache/huggingface/")

    print("\n[OK] Done -- all embeddings generated locally, no API key needed.")


if __name__ == "__main__":
    asyncio.run(main())
