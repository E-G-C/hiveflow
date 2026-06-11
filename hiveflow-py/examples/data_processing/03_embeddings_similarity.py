#!/usr/bin/env python3
"""Data Processing 03: Embeddings, vector store, and similarity search.

Demonstrates the embedding and vector store plugin system:
  1. Generate text embeddings via OpenAI (text-embedding-3-small)
  2. Store vectors in MemoryVectorStore
  3. Search by cosine similarity
  4. Collection management with namespace isolation

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    uv run python examples/data_processing/03_embeddings_similarity.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.embeddings import EmbeddingProviderRegistry
from hiveflow.plugins.embeddings.openai_embeddings import OpenAIEmbeddingProvider
from hiveflow.plugins.vector_stores import CollectionManager, VectorStoreRegistry
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
EMBEDDING_MODEL = "text-embedding-3-small"


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


# -- Sample knowledge base --
DOCUMENTS = [
    {"doc_id": "doc-1", "text": "Python is a high-level programming language known for its readability and versatility."},
    {"doc_id": "doc-2", "text": "Machine learning algorithms learn patterns from data to make predictions."},
    {"doc_id": "doc-3", "text": "Neural networks are computing systems inspired by biological brain structures."},
    {"doc_id": "doc-4", "text": "Docker containers package applications with their dependencies for consistent deployment."},
    {"doc_id": "doc-5", "text": "Kubernetes orchestrates containerized workloads across clusters of machines."},
    {"doc_id": "doc-6", "text": "REST APIs use HTTP methods to create, read, update, and delete resources."},
    {"doc_id": "doc-7", "text": "Quantum computing uses qubits that can exist in superposition states."},
    {"doc_id": "doc-8", "text": "Graph databases store data as nodes and edges, modeling relationships naturally."},
]


async def main() -> None:
    # Configure Azure OpenAI for embeddings
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Check for API key -- Azure RBAC or explicit key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        # Try Azure RBAC via azure-identity
        try:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            # Set up the OpenAI client to use Azure
            os.environ["OPENAI_API_KEY"] = "azure-rbac"  # placeholder, overridden by client
        except ImportError:
            print("ERROR: No OPENAI_API_KEY and azure-identity not installed.")
            print("Install with: pip install azure-identity")
            return
    else:
        token_provider = None

    # -- 1. Create embedding provider --
    print_section("1. Embedding provider setup")

    provider = OpenAIEmbeddingProvider()
    print(f"  Provider:   {provider.plugin_id}")
    print(f"  Model:      {EMBEDDING_MODEL}")
    print(f"  Dimensions: {provider.embedding_dimension}")
    print(f"  Batch size: {provider.max_batch_size}")
    print(f"  Cost est:   ${provider.estimate_cost(10000):.4f} per 10K tokens")

    # -- 2. Generate embeddings --
    print_section("2. Generate embeddings for {} documents".format(len(DOCUMENTS)))

    # Use the Azure OpenAI embeddings endpoint
    from openai import AsyncAzureOpenAI

    if token_provider:
        client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version="2024-06-01",
        )
    else:
        client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_key=api_key,
            api_version="2024-06-01",
        )

    texts = [d["text"] for d in DOCUMENTS]
    try:
        response = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    except Exception as e:
        print(f"  ERROR calling Azure OpenAI: {e}")
        print("  Make sure you are on an allowed network (VNet/firewall rules).")
        return
    vectors = [item.embedding for item in response.data]

    print(f"  Embedded {len(vectors)} texts")
    print(f"  Vector dimensions: {len(vectors[0])}")
    print(f"  Total tokens used: {response.usage.total_tokens}")

    # -- 3. Store in MemoryVectorStore --
    print_section("3. Store vectors in MemoryVectorStore")

    store = MemoryVectorStore()
    await store.add(vectors, DOCUMENTS)

    count = await store.count()
    print(f"  Documents stored: {count}")

    # -- 4. Similarity search --
    print_section("4. Similarity search")

    queries = [
        "How do AI systems learn from data?",
        "What is container orchestration?",
        "Tell me about quantum physics",
    ]

    for query in queries:
        print(f"  Query: {query!r}")

        # Embed the query
        q_response = await client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
        query_vec = q_response.data[0].embedding

        # Search
        results = await store.search(query_vec, top_k=3)

        for rank, (doc, score) in enumerate(results, 1):
            print(f"    {rank}. [{score:.3f}] {doc['text'][:70]}...")
        print()

    # -- 5. Collection management --
    print_section("5. Collection management (namespace isolation)")

    mgr = CollectionManager(store, collection_prefix="demo_", persist=False)
    print(f"  Collection name: {mgr.collection_name('session-abc')}")
    print(f"  Persist mode:    False (ephemeral)")

    await mgr.cleanup()
    count_after = await store.count()
    print(f"  After cleanup:   {count_after} documents (cleared)")

    # -- 6. CRUD operations --
    print_section("6. CRUD operations")

    # Re-add a subset
    await store.add(vectors[:3], DOCUMENTS[:3])
    print(f"  Added 3 documents:  count={await store.count()}")

    # Delete one
    await store.delete(["doc-2"])
    print(f"  Deleted doc-2:      count={await store.count()}")

    # Clear all
    await store.clear()
    print(f"  Cleared all:        count={await store.count()}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
