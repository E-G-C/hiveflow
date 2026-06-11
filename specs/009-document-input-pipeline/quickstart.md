# Quickstart: Document Input Pipeline Enhancements

**Feature**: 009-document-input-pipeline

---

## 1. Instructions from a File

```python
from hiveflow import HiveFlow

hive = HiveFlow()

# Load complex instructions from a file
session = await hive.run(
    team="content_rewriter",
    task="",
    instructions_file="./prompts/rewrite-instructions.md",
    documents=["./transcript.txt"],
)
```

## 2. Load Documents from Bytes

```python
from hiveflow.plugins.documents import DocumentLoaderPlugin

# Works with any loader — default uses temp file delegation
loader = get_loader_for_extension(".pdf")
doc = await loader.load_from_bytes(pdf_bytes, "contract.pdf")
print(doc.name, doc.chunk_count)
```

## 3. Summary Document Mode

```yaml
# In team config — agent sees condensed summaries, not raw chunks
agents:
  - id: planner
    role: "Project planner"
    document_mode: summary
    max_document_tokens: 500
```

```python
# Agent receives single summary chunk per document
# Summaries are cached — second agent reuses without re-calling LLM
```

## 4. Document Variables in Prompts

```python
from hiveflow.core.prompts import PromptTemplate

template = PromptTemplate(
    "You have $document_count documents: $document_names.\n"
    "Summary: $document_summary\n\n"
    "Task: $task",
    name="doc_aware",
)
# Variables auto-populated from workflow state
```
