"""Example: Prompt Template Library — Families, Categories, Dotted-Path Variables.

Demonstrates how to:
1. Browse the 16 built-in prompt templates across 15 categories
2. Use dotted-path variable resolution (${task.description})
3. Auto-detect prompt family from model names
4. Render categorized templates with state data

No live LLM needed — this is purely about prompt construction.

Usage:
    uv run python examples/config_operations/03_prompt_templates.py
"""

import asyncio

from hiveflow.core.prompts import (
    PromptCategory,
    PromptFamily,
    PromptTemplate,
    detect_family,
    get_default_library,
    resolve_dotted_path,
)


async def main() -> None:
    # -- 1. Browse the template library ----------------------------------------
    print("--- 1. Built-in prompt library ---")
    lib = get_default_library()
    templates = lib.list_templates()
    print(f"Total templates: {len(templates)}")
    for name in templates:
        t = lib.get(name)
        cat = t.category.value if t.category else "—"
        print(f"  {name:30s} category={cat}")

    # -- 2. All 15 categories covered ------------------------------------------
    print(f"\n--- 2. Categories ({len(PromptCategory)} total) ---")
    for cat in PromptCategory:
        print(f"  {cat.value}")

    # -- 3. Prompt family auto-detection ---------------------------------------
    print("\n--- 3. Prompt family detection ---")
    models = [
        "openai:gpt-4o",
        "anthropic:claude-sonnet-4-20250514",
        "azure:gpt-4o-mini",
        "ollama:llama3",
        "lmstudio:mistral-7b",
        "granite:13b-instruct",
        "ibm:granite-20b",
    ]
    for model in models:
        family = detect_family(model)
        print(f"  {model:40s} -> {family.value}")

    # -- 4. Dotted-path variable resolution ------------------------------------
    print("\n--- 4. Dotted-path resolution ---")
    state = {
        "task": {"description": "Analyze market trends", "subtopic": "AI industry"},
        "config": {"language": "english", "tone": "analytical"},
        "agent": {"id": "researcher", "model": "gpt-4o"},
    }

    paths = ["task.description", "task.subtopic", "config.language", "agent.model", "missing.path"]
    for path in paths:
        value = resolve_dotted_path(state, path)
        print(f"  {path:20s} -> {value}")

    # -- 5. Render templates with dotted-path vars -----------------------------
    print("\n--- 5. Template rendering with dotted paths ---")
    template = PromptTemplate(
        "You are a ${config.tone} analyst studying ${task.description}.\n"
        "Focus on: ${task.subtopic}.\n"
        "Language: ${config.language}.",
        name="custom_analyst",
    )
    rendered = template.render(state)
    print(f"  Rendered:\n  {rendered}")

    # -- 6. Render a built-in categorized template -----------------------------
    print("\n--- 6. Built-in template rendering ---")
    code_gen = lib.get("code_generation")
    if code_gen:
        result = code_gen.render(
            language="Python",
            task="implement a binary search",
            requirements="O(log n) time, handle empty list edge case",
        )
        print(f"  code_generation template:\n  {result[:200]}...")

    # -- 7. Sub-task decomposition template ------------------------------------
    print("\n--- 7. Sub-task decomposition ---")
    decomp = lib.get("sub_task_decomposition")
    if decomp:
        result = decomp.render(
            task="Build a customer dashboard",
            context="React frontend, FastAPI backend, PostgreSQL database",
        )
        print(f"  {result[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())
