# API Contracts: Document Input Pipeline Enhancements

**Feature**: 009-document-input-pipeline  
**Date**: 2026-02-27

> This feature extends internal Python APIs. No new HTTP endpoints.

---

## Contract 1: HiveFlow.run() (extended)

```python
async def run(
    self,
    team: str | dict[str, Any] | Any,
    task: str,
    *,
    documents: list[str | dict[str, str]] | None = None,
    initial_state: dict[str, Any] | None = None,
    checkpoint: bool = False,
    instructions_file: str | None = None,  # NEW
) -> WorkflowSession:
    """Run a workflow with optional instructions from file.

    Args:
        instructions_file: Path to a text file containing instructions.
            Mutually exclusive with non-empty task.

    Raises:
        ValueError: If both task (non-empty) and instructions_file provided.
        FileNotFoundError: If instructions_file doesn't exist.
    """
```

## Contract 2: DocumentLoaderPlugin.load_from_bytes()

```python
class DocumentLoaderPlugin(BasePlugin):
    # Existing abstract methods unchanged

    async def load_from_bytes(self, data: bytes, filename: str) -> Document:
        """Load a document from in-memory bytes.

        Default implementation writes to a temp file and delegates to load().
        Subclasses may override for direct byte-stream processing.

        Args:
            data: Raw file bytes.
            filename: Original filename (for extension detection and naming).

        Returns:
            Parsed Document.

        Raises:
            ValueError: If data is empty (zero-length bytes).
        """
```

## Contract 3: DocumentPipeline.generate_summaries()

```python
class DocumentPipeline:
    async def generate_summaries(
        self,
        documents: list[dict[str, Any]],
        state: dict[str, Any],
        llm_provider: Any,
        max_tokens: int = 200,
    ) -> dict[str, str]:
        """Generate LLM-based summaries for documents.

        Args:
            documents: Document state dicts to summarize.
            state: Workflow state (for caching under _document_summaries).
            llm_provider: LLM provider for summary generation.
            max_tokens: Max tokens per summary.

        Returns:
            Dict mapping document name → summary string.
        """
```
