# SDK API Contract: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18

## Public API Changes

### `HiveFlow` / `WorkflowEngine.execute()` — Extended Signature

The primary entry point gains two new optional parameters.

```python
# Current signature (WorkflowEngine.execute):
async def execute(
    self,
    agents: dict[str, Agent],
    initial_state: dict[str, Any],
) -> WorkflowResult

# Extended signature:
async def execute(
    self,
    agents: dict[str, Agent],
    initial_state: dict[str, Any],
    *,
    documents: list[str | dict[str, str]] | None = None,
    instructions_file: str | None = None,
) -> WorkflowResult
```

### Parameters

#### `documents`

- **Type**: `list[str | dict[str, str]] | None`
- **Default**: `None` (no documents loaded)
- **Behavior**:
  - `str` items: interpreted as file paths, resolved relative to
    working directory
  - `dict` items: inline content with required keys `name` (str) and
    `content` (str)
  - Mixed lists (paths and dicts) are supported
- **Validation**:
  - File paths must resolve within the working directory or configured
    allowed-paths list
  - Total size of all documents must not exceed 50 MB (configurable
    via `max_document_bytes` config)
  - Duplicate document names are rejected
  - Unsupported file extensions raise `ValueError`
  - Missing files raise `FileNotFoundError`

#### `instructions_file`

- **Type**: `str | None`
- **Default**: `None`
- **Behavior**: Reads the file as UTF-8 and uses its content as the
  `instructions` (task) string
- **Validation**:
  - Mutually exclusive with `instructions` — providing both raises
    `ValueError`
  - Same path security rules as `documents`

### State Shape After Loading

```python
state = {
    "task": "Rewrite this transcript as a blog post",
    "documents": [
        {
            "name": "reports/transcript.txt",
            "format": "txt",
            "size_bytes": 24500,
            "chunks": [
                {"index": 0, "content": "Hello everyone..."},
                {"index": 1, "content": "...key insight..."}
            ],
            "chunk_count": 2,
            "total_tokens_estimate": 6100
        }
    ],
    "document_summary": "1 document loaded: reports/transcript.txt (2 chunks, ~6100 tokens)",
    # ... existing state keys ...
}
```

### Error Conditions

| Condition | Exception | Message pattern |
|-----------|-----------|-----------------|
| File not found | `FileNotFoundError` | `"Document not found: {path}"` |
| Unsupported format | `ValueError` | `"Unsupported document format '.xyz'. Supported: .txt, .csv, ..."` |
| Path traversal | `ValueError` | `"Document path '{path}' is outside allowed directories"` |
| Size limit exceeded | `ValueError` | `"Total document size ({n} MB) exceeds limit ({limit} MB)"` |
| Mutual exclusivity | `ValueError` | `"'instructions' and 'instructions_file' are mutually exclusive"` |
| Duplicate names | `ValueError` | `"Duplicate document name: '{name}'"` |
| Missing scoping ref | `ValueError` | `"Agent '{id}' references unknown document: '{name}'"` |

### DocumentPipeline Public API

```python
class DocumentPipeline:
    def __init__(
        self,
        registry: DocumentLoaderRegistry,
        working_dir: Path | None = None,
        allowed_paths: list[Path] | None = None,
        max_total_bytes: int = 50 * 1024 * 1024,  # 50 MB
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None: ...

    async def load(
        self,
        inputs: list[str | dict[str, str]],
    ) -> tuple[list[dict[str, Any]], str]:
        """Load and process documents.

        Returns:
            Tuple of (documents state list, document summary string)
        """
        ...

    async def load_instructions_file(
        self, path: str,
    ) -> str:
        """Read instructions from file.

        Returns:
            File content as string
        """
        ...

    def scope_for_agent(
        self,
        documents: list[dict[str, Any]],
        agent_def: AgentDefinition,
        task: str,
    ) -> list[dict[str, Any]]:
        """Filter documents per agent scoping config.

        Returns:
            Filtered/transformed document list
        """
        ...
```
