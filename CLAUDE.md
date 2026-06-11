# hiveflow Development Guidelines

**IMPORTANT: Read and follow all instructions in AGENTS.md before starting any work.** It contains mandatory rules for issue tracking (bd/beads), Python tooling (uv), library preferences, documentation, changelog maintenance, and session-completion workflow.


## Active Technologies
- Python 3.11+ (no `from __future__ import annotations`)
- pydantic >=2.9.2, pydantic-settings
- openai >=1.52.0, anthropic >=0.39.0
- azure-identity >=1.19.0 (optional, `llm-azure` extras)
- structlog >=24.4.0, opentelemetry-api (optional)
- httpx, aiofiles, pyyaml, json-repair, ratelimit, rich
- pypandoc >=1.14, jinja2 >=3.1.4 (optional, `publishers` extras)
- Microsoft Agent Framework
- Python 3.11+ (no `from __future__ import annotations`) + pydantic >=2.9.2, pydantic-settings, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, httpx, aiofiles, pyyaml, json-repair, ratelimit (001-core-architecture)
- File-based JSON for workflow checkpoints; JSON/YAML files for team configs and archetypes (001-core-architecture)
- File-based JSON for workflow checkpoints (`FileCheckpointStorage` in `.hiveflow/checkpoints/`) (004-workflow-engine)
- Python 3.11+ + pydantic >=2.9.2, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, httpx, aiofiles, pyyaml, json-repair (005-agents-and-teams)
- File-based JSON for checkpoints (`.hiveflow/checkpoints/`), JSON/YAML for team configs and archetypes (005-agents-and-teams)
- Python 3.11+ (no `from __future__ import annotations` per constitution §5.1) + pydantic >=2.9.2, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, httpx, aiofiles, pyyaml, json-repair, ratelimit (005-agents-and-teams)
- Python 3.11+ (no `from __future__ import annotations`) + httpx, aiofiles, structlog, pydantic>=2.9.2, pydantic-settings, openai>=1.52.0; new optional: beautifulsoup4, playwright, duckduckgo-search, tavily-python, numpy (006-data-processing-infra)
- In-memory vector store (default); pluggable backends (ChromaDB, FAISS, etc.) via entry points; file-based JSON for checkpoints (existing) (006-data-processing-infra)
- Python 3.11+ (no `from __future__ import annotations`) + pydantic ≥2.9.2, pydantic-settings, openai ≥1.52.0, anthropic ≥0.39.0, structlog ≥24.4.0, httpx, aiofiles, json-repair, ratelimit (008-config-operations)
- File-based JSON for checkpoints (`.hiveflow/checkpoints/`); JSON/YAML for team configs (008-config-operations)
- Python 3.11+ (no `from __future__ import annotations`) + pydantic ≥2.9.2, pydantic-settings, aiofiles, structlog ≥24.4.0 (009-document-input-pipeline)
- File-based (documents loaded from filesystem or in-memory bytes) (009-document-input-pipeline)
- Python 3.11+ (no `from __future__ import annotations`) + pydantic >=2.9.2, pydantic-settings, structlog >=24.4.0, openai >=1.52.0, anthropic >=0.39.0, httpx (014-task-preprocessing)
- In-memory state dict (no persistent storage for preprocessing artifacts) (014-task-preprocessing)

## Project Structure

Main package is `hiveflow/`. Tests in `tests/`. Requirements specs in `requirements/` (files 01-12).

## Code Style

- Python 3.11+: Follow standard conventions
- No `from __future__ import annotations`
- Use pydantic BaseModel for schemas, dataclasses for simple data
- Async-first for I/O operations

## Requirements

Architecture and design decisions are documented in `requirements/`.


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->


