# CLI Reference

HiveFlow provides a command-line interface for running workflows, publishing results, and managing configurations — all without writing Python code.

## CLI Workflow

Every CLI invocation follows this pipeline:

```mermaid
flowchart LR
    A[hiveflow run] --> B[Config Resolution]
    B --> C[Team Loading]
    C --> D[Workflow Execution]
    D --> E[Output Publishing]

    style A fill:#4a90d9,color:#fff
    style B fill:#7b68ee,color:#fff
    style C fill:#e8a838,color:#fff
    style D fill:#da70d6,color:#fff
    style E fill:#50c878,color:#fff
```

## Installation

The CLI is installed automatically with HiveFlow:

```bash
uv sync
hiveflow --help
```

## Commands

### `hiveflow run`

Execute a workflow from the command line.

```bash
hiveflow run --template <team-name> [options]
```

#### Required Arguments

| Argument | Description |
|----------|-------------|
| `--template NAME` | Team template name to execute |

#### Optional Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--instructions TEXT` | Inline instructions string (use `-` for stdin) | — |
| `--instructions-file PATH` | Path to instructions file | — |
| `--doc PATH` | Document file path (repeatable, use `-` for stdin) | — |
| `--config PATH` | Path to HiveFlow config file | — |
| `--publish FORMATS` | Comma-separated output formats | — |
| `--output-dir DIR` | Output directory for published files | `./output` |

#### Mutual Exclusions

- `--instructions` and `--instructions-file` cannot be used together
- Only one of `--instructions` or `--doc` can read from stdin (`-`)

## Common Workflows

### Research & Report

The most common pattern — run a research workflow and publish the results:

```mermaid
flowchart LR
    A[Instructions] --> B[hiveflow run]
    B --> C[Research Agents]
    C --> D[Markdown + PDF]

    style A fill:#4a90d9,color:#fff
    style B fill:#7b68ee,color:#fff
    style C fill:#e8a838,color:#fff
    style D fill:#50c878,color:#fff
```

```bash
hiveflow run --template research_report \
    --instructions "Analyze cloud computing trends in 2025" \
    --publish markdown,pdf \
    --output-dir ./reports
```

### Document Analysis

Feed documents into a workflow for summarization or analysis:

```mermaid
flowchart LR
    A[Documents] --> B[hiveflow run]
    B --> C[Analyzer Agents]
    C --> D[Summary Output]

    style A fill:#4a90d9,color:#fff
    style B fill:#7b68ee,color:#fff
    style C fill:#e8a838,color:#fff
    style D fill:#50c878,color:#fff
```

```bash
hiveflow run --template doc_analyzer \
    --doc ./report.pdf \
    --doc ./notes.md \
    --instructions "Summarize the key findings"
```

### Pipeline from stdin

Stream instructions or documents from other commands:

```bash
# Pipe instructions from another command
echo "Analyze recent quantum computing breakthroughs" | \
    hiveflow run --template research_report --instructions -

# Pipe a document from another command
cat report.txt | hiveflow run --template doc_analyzer --doc -
```

## Usage Examples

### Basic Workflow

```bash
hiveflow run --template research_report --instructions "Analyze cloud computing trends"
```

### Instructions from File

```bash
hiveflow run --template research_report --instructions-file ./instructions.md
```

### With Documents

```bash
hiveflow run --template doc_analyzer \
    --doc ./report.pdf \
    --doc ./notes.md \
    --instructions "Summarize the key findings"
```

### Publish to Multiple Formats

```bash
hiveflow run --template research_report \
    --instructions "AI safety analysis" \
    --publish markdown,json,pdf \
    --output-dir ./reports
```

### Read Instructions from stdin

```bash
echo "Analyze recent quantum computing breakthroughs" | \
    hiveflow run --template research_report --instructions -
```

### Read Document from stdin

```bash
cat report.txt | hiveflow run --template doc_analyzer --doc -
```

### Custom Config File

```bash
hiveflow run --template research_report \
    --config ./my_config.json \
    --instructions "Custom configuration example"
```

### With Azure OpenAI

```bash
AZURE_OPENAI_ENDPOINT=https://my-resource.openai.azure.com \
    hiveflow run --template research_report \
    --instructions "Analyze renewable energy trends"
```

### With Model Override

```bash
HIVEFLOW_SMART_LLM=anthropic:claude-sonnet-4-20250514 \
    hiveflow run --template content_creation \
    --instructions "Write a blog post about AI"
```

## Exit Codes

| Code | Meaning |
|:----:|---------|
| 0 | Success |
| 1 | Usage error (invalid arguments) |
| 2 | File error (file not found) |
| 3 | Workflow execution error |

## Environment Variables

The CLI respects all HiveFlow environment variables. Key ones:

| Variable | Description |
|----------|-------------|
| `HIVEFLOW_FAST_LLM` | Fast model tier |
| `HIVEFLOW_SMART_LLM` | Smart model tier |
| `HIVEFLOW_STRATEGIC_LLM` | Strategic model tier |
| `OPENAI_API_KEY` | OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint |

See [Configuration](../configuration.md) for the full list.

## Troubleshooting

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Template not found: X` | Team template name doesn't match any config | Check available templates in your config directory |
| `Cannot use --instructions with --instructions-file` | Mutual exclusion violated | Use only one of the two flags |
| `File not found: X` | Document path doesn't exist | Verify the path with `ls` / `dir` before running |
| `Workflow execution error (exit 3)` | Agent or LLM failure during execution | Check API keys are set and model endpoints are reachable |
| `No API key configured` | Missing `OPENAI_API_KEY` or equivalent | Export the required API key environment variable |

### Debugging Tips

> **Tip:** Set `HIVEFLOW_LOG_LEVEL=debug` to get verbose output from the workflow engine, including agent prompts and LLM responses.

```bash
# Verbose debug run
HIVEFLOW_LOG_LEVEL=debug hiveflow run --template research_report \
    --instructions "Debug test"

# Verify your config is being loaded correctly
hiveflow run --template research_report --config ./my_config.json \
    --instructions "Config test" 2>&1 | head -20
```
