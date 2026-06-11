# Streaming Examples

Examples demonstrating HiveFlow's real-time event streaming system.

## Examples

| # | Script | What it shows | API Key? |
|---|--------|---------------|:--------:|
| 01 | `01_event_streaming.py` | Event callbacks, StreamChannel, JsonLinesWriter | No |

## Running

```bash
uv run python examples/streaming/01_event_streaming.py
```

## Key Concepts

- **Event callbacks** — `engine.on_event()` for simple progress tracking
- **StreamChannel** — Async pub/sub with fan-out to multiple consumers
- **StreamConsumer** — Async iterator over events
- **JsonLinesWriter** — Persist events to JSONL files
- **26 event types** — From `TOKEN` to `ASSEMBLY_COMPLETE`
