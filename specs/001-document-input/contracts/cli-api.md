# CLI API Contract: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18

## New CLI Entry Point

**Binary**: `hiveflow` (registered via `[project.scripts]` in
`pyproject.toml`)

**Module**: `hiveflow.cli.main:main`

## Command: `hiveflow run`

### Synopsis

```
hiveflow run --template <name> [--instructions <text>]
             [--instructions-file <path>] [--doc <path>]...
             [--config <path>]
```

### Arguments

| Flag | Type | Required | Description |
|------|------|----------|-------------|
| `--template` | `str` | Yes | Team template name |
| `--instructions` | `str` | No | Inline instructions string |
| `--instructions-file` | `str` | No | Path to instructions file (mutually exclusive with `--instructions`) |
| `--doc` | `str` (repeatable) | No | Document file path (can be specified multiple times) |
| `--config` | `str` | No | Path to HiveFlow config file |

### Stdin Support

| Syntax | Behavior |
|--------|----------|
| `--instructions -` | Read instructions from stdin |
| `--doc -` | Read one document from stdin (named `stdin.txt`) |

**Constraint**: `--instructions -` and `--doc -` cannot both be
specified in the same invocation (stdin cannot be consumed twice).

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success — workflow completed |
| 1 | Usage error (missing args, mutual exclusivity) |
| 2 | File error (not found, path traversal, size limit) |
| 3 | Workflow error (agent failure, unsupported format) |

### Examples

```bash
# Simple: one document
hiveflow run --template content_rewriter \
    --instructions "Rewrite as a blog post" \
    --doc ./transcript.txt

# Multiple documents
hiveflow run --template contract_analyzer \
    --instructions "Identify risks" \
    --doc ./contract.pdf \
    --doc ./amendment.docx

# Instructions from file
hiveflow run --template content_rewriter \
    --instructions-file ./prompts/rewrite-instructions.md \
    --doc ./transcript.txt

# Pipe document from stdin
cat presentation.txt | hiveflow run --template rewriter \
    --instructions "Summarize this" --doc -

# Pipe instructions from stdin
cat prompt.md | hiveflow run --template research_report \
    --instructions -
```

### Output

Workflow result is printed to stdout as JSON:

```json
{
  "status": "completed",
  "final_output": "...",
  "documents_loaded": 2,
  "agents_executed": 3,
  "total_tokens_used": 12500
}
```

Errors are printed to stderr with actionable messages.

Structured logs go to stderr when `--verbose` is specified (future
enhancement, not part of this feature).
