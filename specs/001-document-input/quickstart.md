# Quickstart: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18

## Prerequisites

- Python 3.11+
- HiveFlow installed: `uv pip install hiveflow`
- For extended formats: `uv pip install hiveflow[documents,scraping]`
- A configured LLM provider (OpenAI, Anthropic, or Azure)

## 1. Process a Single Document (CLI)

```bash
hiveflow run --template content_rewriter \
    --instructions "Rewrite this transcript as a blog post" \
    --doc ./transcript.txt
```

The framework will:
1. Load `transcript.txt` using the plain text loader
2. Chunk the content if it exceeds the chunk size
3. Inject the chunked content into the workflow state
4. Run the `content_rewriter` template agents with the document in
   context

## 2. Process a Single Document (SDK)

```python
import asyncio
from hiveflow import WorkflowEngine

async def main():
    # Minimal document workflow
    engine = WorkflowEngine(...)

    result = await engine.execute(
        agents=agents,
        initial_state={"task": "Summarize this document"},
        documents=["./report.pdf"],
    )

    print(result.final_output)

asyncio.run(main())
```

## 3. Use Instructions from a File

For complex, multi-paragraph prompts:

```bash
# CLI
hiveflow run --template research_report \
    --instructions-file ./prompts/detailed-analysis.md \
    --doc ./data.csv
```

```python
# SDK
result = await engine.execute(
    agents=agents,
    initial_state={},
    instructions_file="./prompts/detailed-analysis.md",
    documents=["./data.csv"],
)
```

## 4. Multiple Documents

```bash
hiveflow run --template contract_analyzer \
    --instructions "Identify risks across these documents" \
    --doc ./contract.pdf \
    --doc ./amendment.docx \
    --doc ./terms.txt
```

## 5. Per-Agent Document Scoping

In your team configuration YAML/JSON, specify which documents each
agent should see:

```yaml
agents:
  - id: summarizer
    role: Document Summarizer
    system_prompt: "Summarize the provided document..."
    behavior_type: llm_only
    documents: ["transcript.txt"]
    document_mode: full

  - id: fact_checker
    role: Fact Checker
    system_prompt: "Verify claims against source material..."
    behavior_type: tool_user
    documents: ["transcript.txt", "speaker-bio.md"]
    document_mode: relevant_chunks
    max_document_tokens: 3000

  - id: editor
    role: Final Editor
    system_prompt: "Polish the rewritten content..."
    behavior_type: llm_only
    # No documents — editor works from prior agent output only
```

## 6. Verify It Works

After running a workflow with documents, check the workflow state:

```python
# The state will contain:
assert "documents" in result.state
assert "document_summary" in result.state

# Each document has metadata:
doc = result.state["documents"][0]
assert doc["name"] == "transcript.txt"
assert doc["format"] == "txt"
assert doc["size_bytes"] > 0
assert doc["chunk_count"] >= 1
assert doc["total_tokens_estimate"] > 0
```

## Supported Formats

| Format | Extension | Required Extra |
|--------|-----------|---------------|
| Plain text | `.txt`, `.csv`, `.tsv` | (none — built-in) |
| Markdown | `.md` | (none — built-in) |
| JSON | `.json` | (none — built-in) |
| XML | `.xml` | (none — built-in) |
| PDF | `.pdf` | `hiveflow[scraping]` |
| Word | `.docx` | `hiveflow[documents]` |
| PowerPoint | `.pptx` | `hiveflow[documents]` |
| Excel | `.xlsx` | `hiveflow[documents]` |
| HTML | `.html` | `hiveflow[scraping]` |

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Unsupported document format '.xyz'` | No loader registered for this extension | Check supported formats above; install required extra |
| `Document not found: ./missing.txt` | File does not exist | Verify the file path |
| `Document path is outside allowed directories` | Path traversal detected | Use paths within the working directory |
| `Total document size exceeds limit` | Documents exceed 50 MB total | Reduce document count or configure `max_document_bytes` |
| `'instructions' and 'instructions_file' are mutually exclusive` | Both provided | Use one or the other |
