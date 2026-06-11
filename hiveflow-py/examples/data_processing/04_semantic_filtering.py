#!/usr/bin/env python3
"""Data Processing 04: Semantic filtering of document chunks.

Demonstrates the enhanced 'relevant_chunks' document mode:
  1. Load a large document and chunk it
  2. Configure an embedding provider for semantic filtering
  3. Filter chunks by cosine similarity against a query
  4. Compare output size: full mode vs relevant_chunks mode

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    uv run python examples/data_processing/04_semantic_filtering.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.documents import DocumentPipeline

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
EMBEDDING_MODEL = "text-embedding-3-small"


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def create_large_document(work_dir: Path) -> None:
    """Create a multi-topic document to demonstrate filtering."""
    (work_dir / "research-report.txt").write_text(
        "Chapter 1: Machine Learning Fundamentals\n\n"
        "Machine learning is a subset of artificial intelligence that enables "
        "systems to learn and improve from experience without being explicitly "
        "programmed. Supervised learning uses labeled training data to learn a "
        "mapping from inputs to outputs. Common algorithms include linear "
        "regression, decision trees, and support vector machines.\n\n"
        "Chapter 2: Deep Learning and Neural Networks\n\n"
        "Deep learning uses multi-layered neural networks to learn hierarchical "
        "representations of data. Convolutional neural networks excel at image "
        "recognition, while recurrent neural networks handle sequential data. "
        "Transformer architectures have revolutionized natural language processing "
        "with models like BERT and GPT.\n\n"
        "Chapter 3: Cloud Computing Infrastructure\n\n"
        "Cloud computing delivers computing resources over the internet on a "
        "pay-as-you-go basis. Major providers include AWS, Azure, and GCP. "
        "Key services include virtual machines, object storage, managed databases, "
        "and serverless functions. Container orchestration with Kubernetes has "
        "become the standard for deploying microservices.\n\n"
        "Chapter 4: Quantum Computing\n\n"
        "Quantum computing leverages quantum mechanical phenomena such as "
        "superposition and entanglement to perform computations. Unlike classical "
        "bits, quantum bits (qubits) can exist in multiple states simultaneously. "
        "Potential applications include cryptography, drug discovery, optimization "
        "problems, and materials science simulations.\n\n"
        "Chapter 5: Cybersecurity Best Practices\n\n"
        "Modern cybersecurity requires a defense-in-depth strategy. Key practices "
        "include zero-trust architecture, multi-factor authentication, encryption "
        "at rest and in transit, regular security audits, and incident response "
        "planning. AI-powered threat detection systems are increasingly used to "
        "identify and respond to sophisticated attacks.\n\n"
        "Chapter 6: DevOps and CI/CD\n\n"
        "DevOps combines software development and IT operations to shorten the "
        "development lifecycle. Continuous integration automatically builds and "
        "tests code changes. Continuous deployment automatically releases tested "
        "changes to production. Infrastructure as code tools like Terraform enable "
        "reproducible environment provisioning.\n"
    )


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Set up Azure OpenAI embedding provider
    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    except ImportError:
        print("ERROR: azure-identity not installed.")
        print("Install with: pip install azure-identity")
        return

    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version="2024-06-01",
    )

    # Create an embedding provider adapter
    class AzureEmbeddingAdapter:
        """Adapter wrapping AsyncAzureOpenAI for DocumentPipeline."""
        async def embed(self, texts, model=None):
            resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [item.embedding for item in resp.data]

        async def embed_single(self, text, model=None):
            result = await self.embed([text])
            return result[0]

    embedding_provider = AzureEmbeddingAdapter()

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        create_large_document(work_dir)

        # -- 1. Load document with full mode --
        print_section("1. Load document (full mode)")

        pipeline_full = DocumentPipeline(working_dir=work_dir, chunk_size=300, chunk_overlap=50)
        docs_full, summary = await pipeline_full.load(["research-report.txt"])

        full_chunks = docs_full[0]["chunk_count"]
        full_tokens = docs_full[0]["total_tokens_estimate"]
        print(f"  Document:    research-report.txt")
        print(f"  Chunks:      {full_chunks}")
        print(f"  Total tokens: ~{full_tokens}")

        agent_full = MagicMock()
        agent_full.id = "analyst"
        agent_full.document_mode = "full"
        agent_full.documents = None
        agent_full.max_document_tokens = None

        scoped_full = pipeline_full.scope_for_agent(docs_full, agent_full)
        full_text_len = sum(
            len(c.get("content", ""))
            for d in scoped_full
            for c in d.get("chunks", [])
        )
        print(f"  Full mode output: {full_text_len} chars across {full_chunks} chunks")

        # -- 2. Load document with relevant_chunks mode --
        print_section("2. Filter with relevant_chunks mode")

        pipeline_semantic = DocumentPipeline(
            working_dir=work_dir,
            chunk_size=300,
            chunk_overlap=50,
            embedding_provider=embedding_provider,
            similarity_threshold=0.35,
        )
        docs_semantic, _ = await pipeline_semantic.load(["research-report.txt"])

        query = "What are the applications and future of quantum computing?"
        print(f"  Query: {query!r}")
        print(f"  Similarity threshold: 0.35")

        agent_semantic = MagicMock()
        agent_semantic.id = "analyst"
        agent_semantic.document_mode = "relevant_chunks"
        agent_semantic.documents = None
        agent_semantic.max_document_tokens = None

        scoped_semantic = pipeline_semantic.scope_for_agent(
            docs_semantic, agent_semantic, task=query
        )
        filtered = await pipeline_semantic.filter_relevant_chunks(scoped_semantic)

        filtered_chunks = sum(len(d.get("chunks", [])) for d in filtered)
        filtered_text_len = sum(
            len(c.get("content", ""))
            for d in filtered
            for c in d.get("chunks", [])
        )

        print(f"\n  Results:")
        print(f"    Full mode:            {full_chunks} chunks, {full_text_len} chars")
        print(f"    Relevant chunks mode: {filtered_chunks} chunks, {filtered_text_len} chars")

        if full_text_len > 0:
            reduction = (1 - filtered_text_len / full_text_len) * 100
            print(f"    Reduction:            {reduction:.0f}%")

        # -- 3. Show the relevant chunks --
        print_section("3. Relevant chunks (ranked by similarity)")

        for doc in filtered:
            for chunk in doc.get("chunks", []):
                score = chunk.get("_relevance_score", 0)
                text = chunk.get("content", "")[:80]
                print(f"  [{score:.3f}] {text}...")
            print()

        # -- 4. Test fallback --
        print_section("4. Fallback: no embedding provider")

        pipeline_no_emb = DocumentPipeline(
            working_dir=work_dir,
            chunk_size=300,
            chunk_overlap=50,
            embedding_provider=None,
        )
        docs_fallback, _ = await pipeline_no_emb.load(["research-report.txt"])
        scoped_fallback = pipeline_no_emb.scope_for_agent(
            docs_fallback, agent_semantic, task=query
        )
        fallback_chunks = sum(len(d.get("chunks", [])) for d in scoped_fallback)
        print(f"  Without embedding provider: {fallback_chunks} chunks (full fallback)")
        print(f"  With embedding provider:    {filtered_chunks} chunks (filtered)")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
