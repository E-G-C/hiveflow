# HiveFlow

A reusable, generic multi-agent framework for collaborative LLM workflows.

HiveFlow lets you assemble any multi-step collaborative workflow from universal,
configuration-driven agent definitions — from simple chains to recursive
research pipelines.

## Repository layout

This repository is a **polyglot monorepo** containing two independent
implementations of HiveFlow plus shared, cross-language specifications.

| Path | Contents |
| --- | --- |
| [`hiveflow-py/`](hiveflow-py/) | **Python** implementation — the reference package, tests, docs, and examples. See [hiveflow-py/README.md](hiveflow-py/README.md). |
| [`hiveflow-js/`](hiveflow-js/) | **TypeScript** rewrite (npm workspace). Greenfield and intentionally not API-compatible with the Python package. See [hiveflow-js/README.md](hiveflow-js/README.md). |
| [`requirements/`](requirements/) | Shared, cross-language requirements and design specifications. |
| [`specs/`](specs/) | Shared spec-driven-development artifacts. |

The Python implementation is the feature reference. Feature parity between the
two implementations is tracked in
[requirements/15-typescript-parity-matrix.md](requirements/15-typescript-parity-matrix.md).

## Getting started

### Python

```bash
cd hiveflow-py
uv venv
uv sync
uv run pytest
```

See [hiveflow-py/README.md](hiveflow-py/README.md) for the full guide,
architecture overview, and documentation index.

### TypeScript

```bash
cd hiveflow-js
npm install
npm run build
```

See [hiveflow-js/README.md](hiveflow-js/README.md) for the current scope,
demos, and commands.

## License

MIT License.
