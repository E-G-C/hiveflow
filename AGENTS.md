# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get
started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT
complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs
   follow-up
1. **Run quality gates** (if code changed) - Tests, linters, builds
2. **Update issue status** - Close finished work, update in-progress items
3. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
1. **Clean up** - Clear stashes, prune remote branches
2. **Verify** - All changes committed AND pushed
3. **Hand off** - Provide context for next session

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

Use 'bd' for task tracking

## Python Tooling — uv

Always use virtual environments for Python work to ensure dependency isolation
and reproducibility. This project uses **uv** as the Python package manager,
virtual environment manager, and script runner. Do NOT use `pip`, `pip install`,
`python -m venv`, or `virtualenv` directly.

> **Location:** All Python sources, tests, and `pyproject.toml` live in the
> **`hiveflow-py/`** directory. Run every `uv` / `pytest` / `ruff` / `mypy`
> command from there (`cd hiveflow-py`). The TypeScript implementation lives in
> `hiveflow-js/`.

### Quick Reference

```bash
uv venv                # Create a virtual environment (.venv)
uv sync                # Install/sync all dependencies from pyproject.toml / uv.lock
uv add <package>       # Add a dependency
uv remove <package>    # Remove a dependency
uv run <command>       # Run a command inside the virtual environment
uv pip list            # List installed packages (inside the venv)
```

### Rules

- Don't use `from __future__ import annotations` as we target Python 3.11+ which supports postponed annotations natively
- **Always use `uv`** for installing, adding, removing, or syncing packages.
- **Always activate the virtual environment** before testing or executing any
  Python code:
  ```powershell
  # PowerShell / Windows
  .venv\Scripts\Activate.ps1
  ```
  ```bash
  # Bash / Linux / macOS
  source .venv/bin/activate
  ```
  Alternatively, prefix commands with `uv run` to execute them inside the venv
  without explicit activation.
- If a `.venv` directory does not exist yet, create one with `uv venv` before
  proceeding.
- Use `uv sync` after cloning the repo or pulling changes to ensure dependencies
  are up to date.
- **Never run `pip install`** — use `uv add` for new dependencies or `uv sync`
  to restore from the lock file.

## Library Preferences

**Prefer Microsoft libraries and frameworks** when a suitable option exists:

| Domain                  | Preferred                        | Avoid unless necessary          |
| ----------------------- | -------------------------------- | ------------------------------- |
| Agent / orchestration   | Microsoft Agent Framework        | LangChain, CrewAI               |
| AI model access         | `azure-ai-inference`, OpenAI SDK | LangChain wrappers              |
| Evaluation              | `azure-ai-evaluation`            | Custom or third-party eval libs |
| Tracing / observability | OpenTelemetry + Azure Monitor    | LangSmith                       |

- Only use a non-Microsoft alternative when there is **no Microsoft equivalent**
  that covers the required functionality.
- When in doubt, check the Microsoft Agent Framework and Azure AI SDK docs first
  before reaching for third-party packages.
- Review the [Agent Framework repository](https://github.com/microsoft/agent-framework) and [Agent Framework Samples](https://github.com/microsoft/Agent-Framework-Samples) to learn, research and working examples.

## Documentation

Keep the project well-documented as it evolves. Documentation is not optional — it is part of delivering the work.

- **Update `README.md`** whenever you add features, change configuration, or alter how the project is built or run.
- **Maintain a `CHANGELOG.md`** (or equivalent) to record notable changes, new capabilities, and breaking modifications.
- **Write user-facing guides** for any non-trivial functionality so that someone new to the project can get started quickly.
- **Document architectural decisions** inline or in dedicated docs when introducing significant design choices.
- **Keep code comments meaningful** — explain *why*, not just *what*.
- When closing an issue, ensure any related documentation has been created or updated before marking it done.

## Change Log

Maintain `CHANGELOG.md` at the repository root. Every commit that adds, removes, or changes functionality **must** have a corresponding entry.

- Use [Keep a Changelog](https://keepachangelog.com/) format with sections: Added, Changed, Deprecated, Removed, Fixed, Security.
- Group entries under an `## [Unreleased]` heading until a version is tagged.
- When tagging a release, move unreleased entries under a dated version heading (e.g. `## [0.5.0] - 2026-02-19`).
- Each entry should be a single line describing **what** changed and **why**, not implementation details.
- Reference the relevant issue or task ID when available (e.g. `(T034-T037)`).

## Create examples

Create examples covering the new features you add, and update existing examples if they are affected by your changes. Examples should be clear, concise, and demonstrate the intended usage of the functionality.

## Keep Project Documentation Current

All project documentation must stay in sync with the codebase at all times. Stale docs are worse than no docs.

- **After every feature or fix**: review and update `README.md`, `CHANGELOG.md`, `CLAUDE.md`, and any relevant docs under `docs/` or `specs/`.
- **After dependency changes**: update installation instructions, `pyproject.toml` optional-dependency docs, and environment variable references.
- **After API changes**: update contract docs (`specs/*/contracts/`), example code, and quickstart guides.
- **Before marking work complete**: confirm that a new contributor could follow the docs to set up, run, and understand the feature you just shipped.
- Keep documentation under the `docs` directory updated with detailed explanations, diagrams, architecture decisions, and anything useful for understanding and using the framework.
