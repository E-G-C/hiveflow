# Configuration & Operations Examples

Functional examples for the features introduced in
**008-config-operations** and **009-document-input-pipeline**.

All examples use Azure OpenAI via RBAC (DefaultAzureCredential).
Set `AZURE_OPENAI_ENDPOINT` to run them:

```bash
AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    uv run python examples/config_operations/01_resilient_provider.py
```

| # | File | Feature | Live LLM? |
|---|------|---------|-----------|
| 01 | `01_resilient_provider.py` | ResilientLLMProvider with fallback + cost tracking | ✅ |
| 02 | `02_config_layering.py` | Four-layer config precedence | No (pure config) |
| 03 | `03_prompt_templates.py` | Prompt families, categories, dotted-path variables | No (pure templates) |
| 04 | `04_streaming_events.py` | StreamEvent types, EventMetadata, JsonLinesWriter | ✅ |
| 05 | `05_action_queue.py` | ActionQueue concurrency, timeout, rollback | No (async sim) |
| 06 | `06_instructions_file.py` | instructions_file on HiveFlow.run() | ✅ |
| 07 | `07_load_from_bytes.py` | load_from_bytes() on document loaders | No (file I/O) |
| 08 | `08_document_summary_mode.py` | LLM-based document summary mode | ✅ |
