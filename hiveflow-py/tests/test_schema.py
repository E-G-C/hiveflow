"""Tests for Team Configuration Schema."""

import pytest
from pydantic import ValidationError

from hiveflow.core.schema import (
    AgentBehaviorTypeSchema,
    AgentDefinition,
    AgentIOMapping,
    PublishConfig,
    StateSchema,
    TeamConfiguration,
    WorkflowGraph,
    WorkflowStepDefinition,
    WorkflowStepType,
)


def test_agent_definition_valid():
    """Test valid agent definition."""
    agent = AgentDefinition(
        id="test_agent",
        role="Test Agent",
        system_prompt="You are a test agent.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        tools=[],
        model="openai:gpt-4o",
    )
    assert agent.id == "test_agent"
    assert agent.role == "Test Agent"
    assert agent.behavior_type == AgentBehaviorTypeSchema.LLM_ONLY


def test_agent_definition_invalid_id():
    """Test agent definition with invalid ID."""
    with pytest.raises(ValidationError):
        AgentDefinition(
            id="invalid id!",  # Spaces and special chars not allowed
            role="Test Agent",
            system_prompt="You are a test agent.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )


def test_agent_definition_empty_prompt():
    """Test agent definition with empty system prompt."""
    with pytest.raises(ValidationError):
        AgentDefinition(
            id="test_agent",
            role="Test Agent",
            system_prompt="   ",  # Empty after strip
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )


def test_workflow_step_sequential():
    """Test sequential workflow step."""
    step = WorkflowStepDefinition(
        agent="agent1", type=WorkflowStepType.SEQUENTIAL, next="agent2"
    )
    assert step.agent == "agent1"
    assert step.type == WorkflowStepType.SEQUENTIAL
    assert step.next == "agent2"


def test_workflow_step_conditional_missing_transitions():
    """Test conditional step missing required transitions."""
    with pytest.raises(ValidationError):
        WorkflowStepDefinition(
            agent="agent1",
            type=WorkflowStepType.CONDITIONAL,
            next_on_accept="agent2",
            # Missing next_on_reject
        )


def test_workflow_step_conditional_valid():
    """Test valid conditional workflow step."""
    step = WorkflowStepDefinition(
        agent="reviewer",
        type=WorkflowStepType.CONDITIONAL,
        next_on_accept="writer",
        next_on_reject="reviser",
    )
    assert step.next_on_accept == "writer"
    assert step.next_on_reject == "reviser"


def test_workflow_graph_empty_steps():
    """Test workflow graph with empty steps."""
    with pytest.raises(ValidationError):
        WorkflowGraph(steps=[])


def test_workflow_graph_valid():
    """Test valid workflow graph."""
    steps = [
        WorkflowStepDefinition(
            agent="agent1", type=WorkflowStepType.SEQUENTIAL, next="agent2"
        ),
        WorkflowStepDefinition(
            agent="agent2", type=WorkflowStepType.SEQUENTIAL, next=None
        ),
    ]
    workflow = WorkflowGraph(steps=steps)
    assert len(workflow.steps) == 2


def test_team_configuration_valid():
    """Test valid team configuration."""
    config = TeamConfiguration(
        team_name="test_team",
        description="A test team",
        agents=[
            AgentDefinition(
                id="agent1",
                role="Agent 1",
                system_prompt="You are agent 1.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            )
        ],
        workflow=WorkflowGraph(
            steps=[
                WorkflowStepDefinition(
                    agent="agent1", type=WorkflowStepType.SEQUENTIAL, next=None
                )
            ]
        ),
    )
    assert config.team_name == "test_team"
    assert len(config.agents) == 1


def test_team_configuration_empty_agents():
    """Test team configuration with no agents."""
    with pytest.raises(ValidationError):
        TeamConfiguration(
            team_name="test_team",
            description="A test team",
            agents=[],
            workflow=WorkflowGraph(
                steps=[
                    WorkflowStepDefinition(
                        agent="agent1", type=WorkflowStepType.SEQUENTIAL, next=None
                    )
                ]
            ),
        )


def test_team_configuration_duplicate_agent_ids():
    """Test team configuration with duplicate agent IDs."""
    with pytest.raises(ValidationError):
        TeamConfiguration(
            team_name="test_team",
            description="A test team",
            agents=[
                AgentDefinition(
                    id="agent1",
                    role="Agent 1",
                    system_prompt="You are agent 1.",
                    behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                ),
                AgentDefinition(
                    id="agent1",  # Duplicate ID
                    role="Agent 1 Copy",
                    system_prompt="You are agent 1 copy.",
                    behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                ),
            ],
            workflow=WorkflowGraph(
                steps=[
                    WorkflowStepDefinition(
                        agent="agent1", type=WorkflowStepType.SEQUENTIAL, next=None
                    )
                ]
            ),
        )


def test_team_configuration_unknown_agent_in_workflow():
    """Test team configuration with workflow referencing unknown agent."""
    with pytest.raises(ValidationError):
        TeamConfiguration(
            team_name="test_team",
            description="A test team",
            agents=[
                AgentDefinition(
                    id="agent1",
                    role="Agent 1",
                    system_prompt="You are agent 1.",
                    behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                )
            ],
            workflow=WorkflowGraph(
                steps=[
                    WorkflowStepDefinition(
                        agent="unknown_agent",  # Not in agents list
                        type=WorkflowStepType.SEQUENTIAL,
                        next=None,
                    )
                ]
            ),
        )


def test_team_configuration_unknown_agent_in_state_schema():
    """Test team configuration with state schema referencing unknown agent."""
    with pytest.raises(ValidationError):
        TeamConfiguration(
            team_name="test_team",
            description="A test team",
            agents=[
                AgentDefinition(
                    id="agent1",
                    role="Agent 1",
                    system_prompt="You are agent 1.",
                    behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                )
            ],
            workflow=WorkflowGraph(
                steps=[
                    WorkflowStepDefinition(
                        agent="agent1", type=WorkflowStepType.SEQUENTIAL, next=None
                    )
                ]
            ),
            state_schema=StateSchema(
                agent_io={
                    "unknown_agent": AgentIOMapping(  # Not in agents list
                        reads=["input"], writes=["output"]
                    )
                }
            ),
        )


def test_state_schema_with_agent_io():
    """Test state schema with agent I/O mappings."""
    state_schema = StateSchema(
        required_keys=["task", "result"],
        agent_io={
            "agent1": AgentIOMapping(reads=["task"], writes=["result"]),
        },
    )
    assert "task" in state_schema.required_keys
    assert "agent1" in state_schema.agent_io


def test_publish_config_defaults():
    """Test publish config with defaults."""
    config = PublishConfig()
    assert config.formats == []
    assert config.layout == "default"
    assert config.style is None
    assert config.output_dir == "./output"
    assert config.filename == "output"


def test_publish_config_custom():
    """Test publish config with custom values."""
    config = PublishConfig(
        formats=["pdf", "docx"], layout="academic", style="mla", output_dir="/tmp/output"
    )
    assert config.formats == ["pdf", "docx"]
    assert config.layout == "academic"
    assert config.style == "mla"
    assert config.output_dir == "/tmp/output"


def test_load_research_report_template():
    """Test loading the research_report template."""
    from pathlib import Path

    template_path = Path(__file__).parent.parent / "hiveflow" / "templates" / "research_report.json"

    if template_path.exists():
        config = TeamConfiguration.from_json_file(str(template_path))
        assert config.team_name == "research_report"
        assert len(config.agents) > 0
        assert config.workflow is not None
        assert config.state_schema is not None
        assert config.publish is not None
    else:
        pytest.skip("Template file not found")


def test_team_configuration_to_json_schema():
    """Test exporting team configuration as JSON schema."""
    config = TeamConfiguration(
        team_name="test_team",
        description="A test team",
        agents=[
            AgentDefinition(
                id="agent1",
                role="Agent 1",
                system_prompt="You are agent 1.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            )
        ],
        workflow=WorkflowGraph(
            steps=[
                WorkflowStepDefinition(
                    agent="agent1", type=WorkflowStepType.SEQUENTIAL, next=None
                )
            ]
        ),
    )

    schema = config.to_json_schema()
    assert "$defs" in schema or "definitions" in schema
    assert "properties" in schema
