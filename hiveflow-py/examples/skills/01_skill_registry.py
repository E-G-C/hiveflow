"""Example: Skill Registry Discovery and Inspection.

Demonstrates how to discover, list, and inspect Agent Skills
using the SkillRegistry.
"""

from pathlib import Path

from hiveflow.plugins.skills import SkillRegistry


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Create a SkillRegistry pointing at the built-in skills directory
    # ------------------------------------------------------------------
    builtin_dir = Path(__file__).resolve().parent.parent.parent / "hiveflow" / "skills"
    registry = SkillRegistry(builtin_dir=builtin_dir)
    registry.discover()

    # ------------------------------------------------------------------
    # 2. List all discovered skills
    # ------------------------------------------------------------------
    print("Discovered skills:")
    for name in registry.list_skills():
        meta = registry.get_metadata(name)
        print(f"  - {name}: {meta.description[:80]}...")
    print()

    # ------------------------------------------------------------------
    # 3. Load a full skill and inspect it
    # ------------------------------------------------------------------
    skill = registry.get_skill("code-review")
    if skill:
        print(f"Skill: {skill.name}")
        print(f"Source: {skill.source}")
        print(f"Base dir: {skill.base_dir}")
        print(f"Token estimate: ~{skill.token_estimate}")
        print(f"Allowed tools: {skill.metadata.allowed_tools or '(none)'}")
        print(f"\nInstructions preview:\n{skill.instructions[:300]}...")
    print()

    # ------------------------------------------------------------------
    # 4. Generate <available_skills> XML for system prompt injection
    # ------------------------------------------------------------------
    xml = registry.get_prompt_section()
    print("System prompt XML block:")
    print(xml)
    print()

    # ------------------------------------------------------------------
    # 5. Generate full instructions section (for llm_only agents)
    # ------------------------------------------------------------------
    full = registry.get_full_instructions_section(["code-review"])
    print(f"Full instructions section length: {len(full)} chars")


if __name__ == "__main__":
    main()
