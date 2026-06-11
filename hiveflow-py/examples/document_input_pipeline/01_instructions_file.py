#!/usr/bin/env python3
"""Document Input Pipeline 01: Load Instructions from a File.

Demonstrates User Story 1 — the ``instructions_file`` parameter on
``HiveFlow.run()`` that reads a text file as the task string.

What this example covers:
  - Loading instructions from .md and .txt files
  - Mutual exclusivity validation (task vs. instructions_file)
  - Running a real workflow with file-based instructions
  - Using the Azure OpenAI endpoint (or mock fallback)

The Azure endpoint is used live — no mocking of the LLM.

Usage:
    $env:AZURE_OPENAI_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
    uv run python examples/document_input_pipeline/01_instructions_file.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Ensure the repo root is on sys.path for local development
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _helpers import get_provider, is_live, print_kv, print_section

from hiveflow import HiveFlow, HiveFlowConfig, WorkflowStatus
from hiveflow.core.documents import DocumentPipeline
from hiveflow.plugins.llm import LLMProviderRegistry


# ---------------------------------------------------------------------------
# Sample instructions files
# ---------------------------------------------------------------------------

REWRITE_INSTRUCTIONS_MD = """\
# Content Rewriting Instructions

You are a professional content rewriter. Follow these rules:

1. **Tone**: Use a conversational, engaging tone suitable for a tech blog.
2. **Structure**: Break content into short paragraphs with descriptive subheadings.
3. **Audience**: Target intermediate developers familiar with basic concepts.
4. **Length**: Aim for 400–600 words.
5. **Formatting**: Use bullet points for lists, bold for key terms, code blocks
   for technical snippets.

Do NOT include a table of contents. Do NOT use first person.
"""

ANALYSIS_INSTRUCTIONS_TXT = """\
Analyze the document(s) provided and produce a structured report with:

- Executive summary (2-3 sentences)
- Key findings (bullet list)
- Risks and concerns
- Recommended next steps

Keep the report concise — no more than 300 words total.
"""

# ---------------------------------------------------------------------------
# Sample document content
# ---------------------------------------------------------------------------

SAMPLE_TRANSCRIPT = """\
Welcome to our Q4 planning session. Today we'll cover three priorities:

First, we need to finalize the v2.0 launch timeline. Engineering estimates
4 weeks for the remaining API integration work. Design has completed all
mockups and the mobile-responsive layout is ready for implementation.

Second, we should discuss the customer feedback from the beta program.
Key themes: users love the new search feature but find onboarding confusing.
Net Promoter Score improved from 42 to 58.

Third, budget allocation for Q1. We're proposing a 15% increase in R&D
spending to accelerate the AI features roadmap, offset by a 5% reduction
in marketing as we shift to product-led growth.

Action items:
- Alice: Finalize API integration timeline by Friday
- Bob: Draft revised onboarding flow based on feedback
- Carol: Prepare Q1 budget proposal for board review
"""


# ---------------------------------------------------------------------------
# Team configuration for the workflow
# ---------------------------------------------------------------------------

TEAM_CONFIG = {
    "team_name": "content_processor",
    "description": "Process documents according to instructions",
    "agents": [
        {
            "id": "processor",
            "role": "Document Processor",
            "system_prompt": (
                "You are a skilled document processor. Follow the instructions "
                "precisely to transform or analyze the document content provided. "
                "Produce well-structured, professional output."
            ),
            "behavior_type": "llm_only",
            "document_mode": "full",
        },
    ],
    "workflow": {
        "steps": [
            {"agent": "processor", "type": "sequential"},
        ],
    },
}


async def demo_instructions_file_api() -> None:
    """Part 1: Use DocumentPipeline.load_instructions_file() directly."""
    print_section("1. DocumentPipeline.load_instructions_file()")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)

        # Write sample instruction files
        md_path = work_dir / "rewrite-instructions.md"
        md_path.write_text(REWRITE_INSTRUCTIONS_MD, encoding="utf-8")

        txt_path = work_dir / "analysis.txt"
        txt_path.write_text(ANALYSIS_INSTRUCTIONS_TXT, encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)

        # Load markdown instructions
        md_content = await pipeline.load_instructions_file("rewrite-instructions.md")
        print_kv("Markdown file", f"{len(md_content)} chars loaded")
        print(f"    First line: {md_content.splitlines()[0]}")

        # Load plain text instructions
        txt_content = await pipeline.load_instructions_file("analysis.txt")
        print_kv("Text file", f"{len(txt_content)} chars loaded")
        print(f"    First line: {txt_content.splitlines()[0]}")

        # Demonstrate that content is read verbatim (no chunking)
        assert md_content == REWRITE_INSTRUCTIONS_MD
        assert txt_content == ANALYSIS_INSTRUCTIONS_TXT
        print("\n  Content read verbatim.")


async def demo_mutual_exclusivity() -> None:
    """Part 2: Validate mutual exclusivity of task vs instructions_file."""
    print_section("2. Mutual Exclusivity Validation")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        instr_path = work_dir / "instructions.txt"
        instr_path.write_text("Some instructions", encoding="utf-8")

        provider, deployment = get_provider()
        registry = LLMProviderRegistry()
        registry._plugins[provider.plugin_id] = provider

        hf = HiveFlow(llm_registry=registry)

        # Attempt to provide both task and instructions_file
        try:
            await hf.run(
                team=TEAM_CONFIG,
                task="This is a non-empty task",
                instructions_file=str(instr_path),
            )
            print("  ERROR: Should have raised ValueError")
        except ValueError as exc:
            print(f"  Caught expected ValueError:")
            print(f"    {exc}")

        # Attempt with non-existent file
        try:
            await hf.run(
                team=TEAM_CONFIG,
                task="",
                instructions_file=str(work_dir / "nonexistent.md"),
            )
            print("  ERROR: Should have raised FileNotFoundError")
        except (FileNotFoundError, ValueError) as exc:
            print(f"\n  Caught expected error for missing file:")
            print(f"    {type(exc).__name__}: {exc}")


async def demo_hiveflow_run_with_instructions_file() -> None:
    """Part 3: Run a full workflow using instructions_file parameter."""
    print_section("3. HiveFlow.run() with instructions_file")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)

        # Write instructions file to disk
        instr_path = work_dir / "instructions.md"
        instr_path.write_text(ANALYSIS_INSTRUCTIONS_TXT, encoding="utf-8")

        # Set up HiveFlow with provider
        provider, deployment = get_provider()
        registry = LLMProviderRegistry()
        registry._plugins[provider.plugin_id] = provider

        config = HiveFlowConfig(
            FAST_LLM=f"{provider.plugin_id}:{deployment}",
            SMART_LLM=f"{provider.plugin_id}:{deployment}",
            STRATEGIC_LLM=f"{provider.plugin_id}:{deployment}",
        )

        hf = HiveFlow(config=config, llm_registry=registry)

        mode = "Azure OpenAI" if is_live() else "Mock"
        print(f"  Provider: {mode}")
        print(f"  Model:    {provider.plugin_id}:{deployment}")
        print(f"  Instructions file: instructions.md")
        print(f"  Document: (inline transcript)")

        # Pass the transcript as an inline document to avoid path validation
        # issues with temp directories.  The instructions_file parameter loads
        # the file from disk; documents can be file paths *or* inline dicts.
        inline_doc = {
            "name": "transcript.txt",
            "content": SAMPLE_TRANSCRIPT,
        }

        # Run with instructions_file (task="" since they're mutually exclusive)
        session = await hf.run(
            team=TEAM_CONFIG,
            task="",
            instructions_file=str(instr_path),
            documents=[inline_doc],
        )

        print(f"\n  Status: {session.result.status.value}")

        # Show output
        output = (
            session.result.state.get("final_output")
            or session.result.state.get("processor_output", "")
        )
        if output:
            print(f"\n  Output ({len(output.split())} words):")
            print("  " + "-" * 60)
            for line in output.splitlines():
                print(f"  {line}")
        else:
            error = session.result.error
            print(f"  Error: {error}" if error else "  No output produced")


async def demo_empty_instructions_file() -> None:
    """Part 4: Edge case — empty instructions file produces empty task."""
    print_section("4. Edge Case: Empty Instructions File")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        empty_path = work_dir / "empty.txt"
        empty_path.write_text("", encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        content = await pipeline.load_instructions_file("empty.txt")

        print_kv("File", "empty.txt")
        print_kv("Content length", len(content))
        print_kv("Content repr", repr(content))
        print("\n  Empty file -> empty task string (workflow proceeds with no task).")


async def main() -> None:
    print("=" * 64)
    print("  Document Input Pipeline -- 01: Instructions from File")
    print("=" * 64)

    await demo_instructions_file_api()
    await demo_mutual_exclusivity()
    await demo_hiveflow_run_with_instructions_file()
    await demo_empty_instructions_file()

    print_section("Done")
    print("  All instructions_file demonstrations completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
