# Research: Output Pipeline Architecture

**Feature**: 003-output-pipeline
**Date**: 2026-02-20

## R1: Document Conversion Library Selection

### Decision: Consolidate on pypandoc (pandoc) for HTML, PDF, and DOCX

**Rationale**: A single conversion engine simplifies the architecture, reduces
the number of system dependencies, and provides best-in-class fidelity for all
three document formats. Pandoc is the industry-standard document converter.

**Alternatives considered**:

| Library | Format | Verdict | Reason rejected |
|---------|--------|---------|-----------------|
| md2pdf (WeasyPrint) | PDF | Rejected | Requires system-level Pango/GLib; adds a second system dependency alongside pandoc |
| htmldocx | DOCX | Rejected | **Abandoned** — GitHub repo deleted, no release since Aug 2021, stuck at v0.0.6 |
| python-docx direct | DOCX | Rejected | Requires building a custom MD→DOCX AST walker; pandoc already does this better |
| docxtpl | DOCX | Rejected | Template-based only; not suitable for arbitrary Markdown→DOCX from scratch |
| fpdf2 | PDF | Rejected | No CSS layout support; low-level API, basic output quality |
| markdown-pdf | PDF | Rejected | AGPL-3.0 license, incompatible with HiveFlow's MIT license |
| mistune | HTML | Not needed | pypandoc handles MD→HTML; mistune would add a second parser with no benefit |
| markdown-it-py | HTML | Not needed | CommonMark compliance is nice but not required; pypandoc covers it |

### Implementation notes

- `pypandoc.convert_text(content, to='html', format='md')` for HTML
- `pypandoc.convert_text(content, to='docx', format='md', outputfile=path)` for DOCX
- `pypandoc.convert_text(content, to='pdf', format='md', outputfile=path)` for PDF
  (requires LaTeX engine; pandoc uses `pdflatex` or `xelatex` by default)
- All calls are sync (subprocess to pandoc); wrap in `asyncio.to_thread()` for
  async compatibility

## R2: Pandoc Installation Strategy

### Decision: Bundle via pypandoc_binary

**Rationale**: Installing `hiveflow[publishers]` should "just work" with
`uv add`. The `pypandoc_binary` package bundles the pandoc binary (~100 MB),
eliminating any system-level setup. This is the same pattern used by
`playwright` (bundled browsers) and `pypandoc_binary`'s own documentation.

**Alternatives considered**:

| Approach | Verdict | Reason |
|----------|---------|--------|
| Require system pandoc | Rejected | Poor DX; user must install pandoc separately; platform-specific instructions |
| Both (try binary, fall back to system) | Considered | Adds complexity for edge case; pypandoc_binary is sufficient |

### Implementation notes

- `pyproject.toml` publishers extra: `pypandoc>=1.14`, `pypandoc_binary>=1.14`
- pypandoc automatically uses the bundled binary from pypandoc_binary
- PDF output additionally requires a LaTeX engine; document this in quickstart
  (recommend TinyTeX or texlive-xetex)

## R3: Backward Compatibility Strategy for PublisherPlugin

### Decision: Dual-signature support via method overloading

**Rationale**: The existing `PublisherPlugin.publish(content, output_path,
metadata)` signature is a public API contract (Constitution §2.5). New
publishers will implement `publish_payload(payload, config)` as the primary
method. The registry will dispatch to `publish_payload` if available, falling
back to `publish(content=payload.content, ...)` for legacy publishers.

**Alternatives considered**:

| Approach | Verdict | Reason |
|----------|---------|--------|
| Replace signature entirely | Rejected | Breaks backward compatibility (Constitution §2.5) |
| Single method with Union type | Rejected | Ambiguous, hard to type-check |
| Adapter pattern wrapping old publishers | Considered | More complex; dual dispatch is simpler |

### Implementation notes

- `PublisherPlugin` gets a new optional method `publish_payload(payload, config)`
- `PublisherRegistry.publish_all()` calls `publish_payload` when defined,
  otherwise extracts `content` from payload and calls legacy `publish()`
- Old publishers continue working unchanged
- New publishers implement `publish_payload()` and optionally `publish()` too

## R4: Layout Template Format

### Decision: YAML-based layout definitions

**Rationale**: YAML aligns with HiveFlow's "configuration over code" principle
(Constitution §2.1). Layout templates are declarative — they define section
order, required/optional flags, and section-to-payload-field mappings. No
executable logic in layout files.

**Alternatives considered**:

| Approach | Verdict | Reason |
|----------|---------|--------|
| Python dataclass | Rejected | Requires code to define layouts; violates config-over-code |
| Jinja2 templates | Rejected | Mixes rendering with structure definition; overkill for section ordering |
| JSON | Considered | Valid but YAML is more human-friendly and already used for team configs |

### Layout template shape (draft):

```yaml
name: default
description: Standard report layout
sections:
  - id: title
    source: metadata.title
    required: true
  - id: date
    source: metadata.date
    required: true
  - id: toc
    source: auto
    required: false
  - id: executive_summary
    source: sections.executive_summary
    required: false
  - id: content
    source: content
    required: true
  - id: actions
    source: actions
    required: false
  - id: conclusion
    source: sections.conclusion
    required: false
  - id: references
    source: references
    required: false
  - id: appendix
    source: cost_summary
    required: false
```

## R5: Async Wrapper for pypandoc

### Decision: Use asyncio.to_thread() for async compatibility

**Rationale**: pypandoc calls are synchronous (subprocess to pandoc binary).
Constitution §5.4 requires async-first APIs. Wrapping in `asyncio.to_thread()`
provides async compatibility without blocking the event loop, and is the
standard pattern for I/O-bound subprocess calls.

**Implementation notes**:

```python
async def _convert(content: str, to: str, output_file: str | None = None) -> str:
    return await asyncio.to_thread(
        pypandoc.convert_text, content, to, format="md", outputfile=output_file
    )
```

## R6: Callback System Design

### Decision: Simple callable registry with async support

**Rationale**: Callbacks are registered as plain callables (sync or async). The
engine inspects whether a callback is a coroutine function and dispatches
accordingly. This follows Python idioms and requires no framework.

**Implementation notes**:

- `WorkflowEngine.on_complete(callback)` registers a callback
- After workflow execution, engine calls each callback with `ResultPayload`
- Async callbacks are awaited; sync callbacks run in `asyncio.to_thread()`
- Exceptions are caught per-callback and logged (isolation per FR-017)
