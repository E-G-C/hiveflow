# Quickstart: Task Preprocessing

**Branch**: `014-task-preprocessing` | **Date**: 2026-03-05

## Overview

Task preprocessing automatically detects when a task input is too large for agents to process effectively, separates instructions from data, chunks the data into model-appropriate segments, and routes only relevant pieces to each agent. This happens transparently — no code changes are needed for existing workflows below the threshold.

## Basic Usage (Automatic)

Task preprocessing activates automatically when `state["task"]` exceeds a model-derived threshold. No configuration is required for the default behavior.

```python
from hiveflow import HiveFlow

hf = HiveFlow()
result = await hf.run(
    template="document_analysis",
    task=large_document_text,  # 21,000+ words
)
# Preprocessing automatically separates instructions from data,
# chunks data, and routes pieces to appropriate agents.
```

## Configuration

### Global settings (environment or `.env`)

```bash
# Disable preprocessing entirely
HIVEFLOW_TASK_PREPROCESS_DISABLED=false

# Fixed threshold in words (0 = auto-compute from model)
HIVEFLOW_TASK_PREPROCESS_THRESHOLD_OVERRIDE=0

# Tuning ratios (defaults shown)
HIVEFLOW_TASK_CONTEXT_RATIO=0.15
HIVEFLOW_TASK_PIPELINE_FACTOR=0.3
HIVEFLOW_TASK_CHUNK_CONTEXT_RATIO=0.10
HIVEFLOW_TASK_CHUNK_OVERLAP_RATIO=0.10
HIVEFLOW_TASK_TOKENS_PER_WORD=1.35
```

### Team-level overrides (YAML config)

```yaml
name: "document_analysis_team"
agents:
  - id: planner
    role: "Plan document analysis"
    system_prompt: "..."
  - id: worker
    role: "Analyze document section"
    system_prompt: "..."
  - id: assembler
    role: "Combine analysis results"
    system_prompt: "..."

preprocessing:
  threshold_override: 3000  # Force preprocessing at 3000 words
  chunk_context_ratio: 0.15  # Larger chunks for this team
```

## How It Works

1. **Threshold check**: Is `state["task"]` word count > model-derived threshold?
   - If no → pass through unchanged (zero overhead)
   - If yes → continue to step 2

2. **Boundary detection**: Separate instructions from data using structural heuristics
   - Checks: explicit section labels, horizontal rules, code fences, size gradient
   - Fallback: single LLM call if no pattern found

3. **Chunking** (if data ≥ 1 chunk target): Split data into model-appropriate segments with paragraph-boundary preference

4. **Summarization**: Generate compact summary (≤300 words) and per-chunk topic hints

5. **State enrichment**: Add `task_instructions`, `task_data`, `task_data_summary`, `task_data_manifest` to state; set `state["task"]` to instructions only

## Accessing Preprocessed State

After preprocessing, agents automatically receive right-sized context. To access preprocessing results programmatically:

```python
# Check if preprocessing was applied
if "task_instructions" in state:
    instructions = state["task_instructions"]
    chunks = state["task_data"]          # list of chunk dicts
    summary = state["task_data_summary"]  # compact summary
    manifest = state["task_data_manifest"]  # chunk metadata

    for chunk in chunks:
        print(f"Chunk {chunk['chunk_id']}: {chunk['words']} words - {chunk['topic_hint']}")
else:
    # Small task — no preprocessing applied
    task = state["task"]
```

## Fan-Out Over Chunks

Use `source: "task_data"` in a parallel fan-out step to assign one chunk per worker:

```yaml
workflow:
  - agent: planner
    step_type: step
  - agent: worker
    step_type: parallel_fan_out
    source: "task_data"  # Each worker gets one chunk as current_item
  - agent: assembler
    step_type: step
```

## Delegation With Chunk Routing

In collaboration mode, planners can delegate specific chunks:

```python
# Planner can use delegate_task with chunk_ids
await delegate_task(
    task="Analyze the financial projections section",
    agent_id="analyst",
    chunk_ids=["chunk_003"]  # Only this chunk is included
)
```
