"""Example: Loading and validating a team configuration."""

from pathlib import Path

from hiveflow import TeamConfiguration

# Path to the research report template
template_path = Path(__file__).parent.parent / "hiveflow" / "templates" / "research_report.json"

# Load and validate the team configuration
config = TeamConfiguration.from_json_file(str(template_path))

# Display configuration information
print(f"Team: {config.team_name}")
print(f"Description: {config.description}")
print(f"\nAgents ({len(config.agents)}):")
for agent in config.agents:
    print(f"  - {agent.id} ({agent.role}): {agent.behavior_type.value}")
    print(f"    Model: {agent.model}")
    if agent.tools:
        print(f"    Tools: {', '.join(agent.tools)}")

print(f"\nWorkflow ({len(config.workflow.steps)} steps):")
for i, step in enumerate(config.workflow.steps, 1):
    print(f"  {i}. {step.agent} ({step.type.value})")
    if step.next:
        print(f"     -> {step.next}")
    elif step.next_on_accept or step.next_on_reject:
        print(f"     [accept] -> {step.next_on_accept}")
        print(f"     [reject] -> {step.next_on_reject}")

if config.state_schema:
    print("\nState Schema:")
    print(f"  Required keys: {', '.join(config.state_schema.required_keys)}")
    print(f"  Agent I/O mappings: {len(config.state_schema.agent_io)} agents")

if config.publish:
    print("\nPublish Configuration:")
    print(f"  Formats: {', '.join(config.publish.formats)}")
    print(f"  Style: {config.publish.style}")
    print(f"  Output: {config.publish.output_dir}")

# Export JSON schema for documentation
json_schema = config.to_json_schema()
print(f"\nJSON Schema contains {len(json_schema.get('properties', {}))} top-level properties")
