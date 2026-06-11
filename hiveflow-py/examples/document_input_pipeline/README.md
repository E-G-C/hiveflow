# Document Input Pipeline Examples

Comprehensive examples demonstrating the four enhancements from
[spec 009](../../specs/009-document-input-pipeline/spec.md):

1. **Instructions from file** — `HiveFlow.run(instructions_file=...)` 
2. **Load from bytes** — `DocumentLoaderPlugin.load_from_bytes()`
3. **Summary document mode** — `document_mode="summary"` with LLM summaries
4. **Prompt template variables** — `$document_count`, `$document_names`, `$document_summary`

## Examples

| # | Script | What it shows | LLM? |
|---|--------|---------------|:----:|
| 01 | `01_instructions_file.py` | Load instructions from file via HiveFlow.run() | Yes |
| 02 | `02_load_from_bytes.py` | Load documents from in-memory bytes | No |
| 03 | `03_summary_mode.py` | LLM-generated document summaries with caching | Yes |
| 04 | `04_template_variables.py` | Document metadata in prompt templates | Yes |
| 05 | `05_full_pipeline.py` | End-to-end: all 4 enhancements in a single workflow | Yes |

## Running

All examples use a live Azure OpenAI endpoint by default. Set the
`AZURE_OPENAI_ENDPOINT` environment variable:

```bash
# Windows PowerShell
$env:AZURE_OPENAI_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"

# Linux / macOS
export AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com

# Run any example
uv run python examples/document_input_pipeline/01_instructions_file.py
uv run python examples/document_input_pipeline/05_full_pipeline.py
```

The examples fall back to a mock LLM if no endpoint is configured.

## Prerequisites

```bash
uv sync
# Optional: for broader document format support
uv pip install markitdown
```
