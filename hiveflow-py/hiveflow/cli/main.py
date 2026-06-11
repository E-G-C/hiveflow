"""HiveFlow CLI - Command-line interface for running workflows.

Entry point: hiveflow run --template <name> [--instructions <text>]
             [--instructions-file <path>] [--doc <path>]... [--config <path>]
"""

import argparse
import asyncio
import json
import sys
from typing import Any

# Exit codes
EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 1
EXIT_FILE_ERROR = 2
EXIT_WORKFLOW_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="hiveflow",
        description="HiveFlow - Multi-agent workflow framework",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # hiveflow run
    run_parser = subparsers.add_parser("run", help="Execute a workflow")
    run_parser.add_argument(
        "--template",
        required=True,
        help="Team template name",
    )
    run_parser.add_argument(
        "--instructions",
        default=None,
        help="Inline instructions string (use '-' for stdin)",
    )
    run_parser.add_argument(
        "--instructions-file",
        default=None,
        help="Path to instructions file (mutually exclusive with --instructions)",
    )
    run_parser.add_argument(
        "--doc",
        action="append",
        default=None,
        help="Document file path (repeatable, use '-' for stdin)",
    )
    run_parser.add_argument(
        "--config",
        default=None,
        help="Path to HiveFlow config file",
    )
    run_parser.add_argument(
        "--publish",
        default=None,
        help="Comma-separated output formats (e.g., 'markdown,pdf,json')",
    )
    run_parser.add_argument(
        "--output-dir",
        default="./output",
        help="Output directory for published files (default: ./output)",
    )

    return parser


def validate_args(args: argparse.Namespace) -> int | None:
    """Validate parsed arguments. Returns exit code on error, None on success."""
    if args.command is None:
        return EXIT_USAGE_ERROR

    if args.command == "run":
        # Check mutual exclusivity of instructions and instructions_file
        if args.instructions is not None and args.instructions_file is not None:
            print(
                "Error: --instructions and --instructions-file are mutually exclusive",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        # Check dual stdin usage
        stdin_from_instructions = args.instructions == "-"
        stdin_from_doc = args.doc is not None and "-" in args.doc
        if stdin_from_instructions and stdin_from_doc:
            print(
                "Error: cannot read both --instructions and --doc from stdin",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

    return None


def resolve_stdin_inputs(args: argparse.Namespace) -> argparse.Namespace:
    """Replace '-' placeholders with actual stdin content."""
    stdin_content: str | None = None

    def get_stdin() -> str:
        nonlocal stdin_content
        if stdin_content is None:
            stdin_content = sys.stdin.read()
        return stdin_content

    if args.instructions == "-":
        args.instructions = get_stdin()

    if args.doc is not None:
        resolved_docs = []
        for d in args.doc:
            if d == "-":
                # Inline content from stdin
                resolved_docs.append({"name": "stdin.txt", "content": get_stdin()})
            else:
                resolved_docs.append(d)
        args.doc = resolved_docs

    return args


async def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the workflow based on parsed arguments.

    Returns:
        Workflow result dict for JSON output.
    """
    from pathlib import Path

    from hiveflow.core.documents import DocumentPipeline
    from hiveflow.core.schema import TeamConfiguration
    from hiveflow.core.workflow import WorkflowEngine, WorkflowStep

    # Load template
    template_path = Path(args.template)
    if template_path.is_file():
        if template_path.suffix in (".yaml", ".yml"):
            config = TeamConfiguration.from_yaml_file(str(template_path))
        else:
            config = TeamConfiguration.from_json_file(str(template_path))
    else:
        # Try loading from default templates directory
        from hiveflow.core.teams import TeamTemplateLibrary

        lib = TeamTemplateLibrary.default()
        template_dict = lib.get(args.template)
        if template_dict is None:
            raise FileNotFoundError(
                f"Template not found: '{args.template}'. "
                f"Available: {', '.join(lib.list_templates()) or '(none)'}"
            )
        config = TeamConfiguration(**template_dict)

    # Build initial state
    initial_state: dict[str, Any] = {}
    if args.instructions is not None:
        initial_state["task"] = args.instructions

    # Build document list
    documents: list[str | dict[str, str]] | None = None
    if args.doc:
        documents = args.doc

    # Create document pipeline
    pipeline = DocumentPipeline()

    # Build workflow engine
    steps = [
        WorkflowStep(
            agent=step.agent,
            step_type=step.type.value,
            next_step=step.next,
            next_on_accept=step.next_on_accept,
            next_on_reject=step.next_on_reject,
        )
        for step in config.workflow.steps
    ]
    engine = WorkflowEngine(steps, document_pipeline=pipeline)

    # Build agents (requires LLM provider — deferred for full integration)
    from hiveflow.core.agent import Agent

    agents: dict[str, Agent] = {}
    for agent_def in config.agents:
        agents[agent_def.id] = Agent.from_definition(agent_def)

    # Execute
    result = await engine.execute(
        agents=agents,
        initial_state=initial_state,
        documents=documents,
        instructions_file=args.instructions_file,
    )

    return {
        "status": result.status.value,
        "final_output": result.state.get("final_output", ""),
        "documents_loaded": len(result.state.get("documents", [])),
        "agents_executed": len(result.step_results),
    }


def main() -> None:
    """Main entry point for the hiveflow CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(EXIT_USAGE_ERROR)

    # Validate
    error_code = validate_args(args)
    if error_code is not None:
        sys.exit(error_code)

    # Resolve stdin
    args = resolve_stdin_inputs(args)

    if args.command == "run":
        try:
            result = asyncio.run(run_workflow(args))
            print(json.dumps(result, indent=2, default=str))
            sys.exit(EXIT_SUCCESS)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(EXIT_FILE_ERROR)
        except ValueError as e:
            error_msg = str(e)
            if "mutually exclusive" in error_msg:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(EXIT_USAGE_ERROR)
            elif "path" in error_msg.lower() or "traversal" in error_msg.lower():
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(EXIT_FILE_ERROR)
            else:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(EXIT_WORKFLOW_ERROR)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(EXIT_WORKFLOW_ERROR)


if __name__ == "__main__":
    main()
