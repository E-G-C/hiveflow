# Document Workflow Examples

Examples demonstrating HiveFlow's document processing capabilities — loading,
chunking, scoping, retrieval, and multi-document pipelines.

## Examples

| # | Script | What it shows | LLM? |
|---|--------|---------------|:----:|
| 01 | `01_document_pipeline.py` | Load, chunk, scope documents (no LLM) | No |
| 02 | `02_document_summarizer.py` | Analyst + writer summarize a document | Yes |
| 03 | `03_document_qa.py` | Q&A with DocumentRetrieverTool | Yes |
| 04 | `04_multi_doc_report.py` | Per-agent document scoping | Yes |
| 05 | `05_document_workflow.py` | Full document-driven workflow patterns | Partial |

## Running

```bash
# No-LLM example (pure data pipeline):
uv run python examples/document_workflows/01_document_pipeline.py

# With Azure OpenAI (default for LLM examples):
uv run python examples/document_workflows/02_document_summarizer.py

# Override provider:
uv run python examples/document_workflows/03_document_qa.py --provider openai
```

## Key Concepts

- **DocumentPipeline** — loads files, chunks content, estimates tokens
- **DocumentLoaderRegistry** — extensible registry of format loaders (txt, md, docx, pdf, etc.)
- **Document scoping** — `document_mode` controls what each agent sees: `full`, `metadata_only`, `none`
- **DocumentRetrieverTool** — on-demand chunk retrieval for `tool_user` agents
- **Per-agent filtering** — `documents` field on agent definition restricts which docs are visible

## Data Files

Sample documents are embedded in the scripts or included alongside them.
Drop any supported file (txt, md, docx, pdf, csv, json, xml, html, xlsx, pptx)
into the working directory and the pipeline will auto-discover it.
