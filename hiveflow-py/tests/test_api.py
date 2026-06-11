"""Tests for FastAPI Backend API extensions."""

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from hiveflow.api import _active_workflows, create_app
from hiveflow.core.config import HiveFlowConfig


@pytest.fixture
def client():
    """Create a test client for the API."""
    from fastapi.testclient import TestClient

    app = create_app(HiveFlowConfig())
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_workflows():
    """Clear active workflows between tests."""
    _active_workflows.clear()
    yield
    _active_workflows.clear()


# --- Health & Config ---


class TestExistingEndpoints:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_config(self, client):
        response = client.get("/config")
        assert response.status_code == 200
        data = response.json()
        assert "FAST_LLM" in data
        assert "SMART_LLM" in data


# --- Templates ---


class TestTemplatesEndpoints:
    def test_list_templates(self, client):
        response = client.get("/templates")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert isinstance(data["templates"], list)
        # Should include research_report from bundled templates
        names = [t["name"] for t in data["templates"]]
        assert "research_report" in names

    def test_list_templates_structure(self, client):
        response = client.get("/templates")
        data = response.json()
        for tpl in data["templates"]:
            assert "name" in tpl
            assert "description" in tpl
            assert "agent_count" in tpl
            assert isinstance(tpl["agent_count"], int)

    def test_get_template(self, client):
        response = client.get("/templates/research_report")
        assert response.status_code == 200
        data = response.json()
        assert data["team_name"] == "research_report"
        assert "agents" in data
        assert "workflow" in data
        assert len(data["agents"]) == 6

    def test_get_template_not_found(self, client):
        response = client.get("/templates/nonexistent_template")
        assert response.status_code == 404

    def test_generate_template(self, client):
        response = client.post("/templates/generate", json={
            "task_description": "Write a blog post about AI safety",
        })
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "workflow" in data
        assert len(data["agents"]) >= 2

    def test_generate_template_with_options(self, client):
        response = client.post("/templates/generate", json={
            "task_description": "Research quantum computing",
            "agent_types": ["researcher", "writer"],
            "include_review": False,
        })
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data

    def test_generate_template_missing_task(self, client):
        response = client.post("/templates/generate", json={})
        assert response.status_code == 400
        assert "task_description" in response.json()["detail"]


# --- Tools ---


class TestToolsEndpoint:
    def test_list_tools(self, client):
        response = client.get("/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)


# --- Team Validation ---


class TestTeamValidation:
    def test_validate_valid_team(self, client):
        response = client.get("/templates/research_report")
        team_config = response.json()

        response = client.post("/teams/validate", json=team_config)
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["agents"] == 6

    def test_validate_invalid_team(self, client):
        response = client.post("/teams/validate", json={"invalid": "config"})
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "error" in data


# --- Workflow Lifecycle ---


class TestWorkflowEndpoints:
    def test_list_workflows_empty(self, client):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert response.json()["workflows"] == []

    def test_get_workflow_not_found(self, client):
        response = client.get("/workflows/nonexistent-id")
        assert response.status_code == 404


# --- Workflow Resume ---


class TestResumeEndpoint:
    def test_resume_not_found(self, client):
        response = client.post(
            "/workflows/nonexistent/resume",
            json={"action": "approve"},
        )
        assert response.status_code == 404

    def test_resume_not_paused(self, client):
        # Create a mock "running" workflow
        _active_workflows["test-wf"] = {
            "status": "running",
            "engine": None,
            "agents": {},
            "channel": None,
            "result": None,
        }
        response = client.post(
            "/workflows/test-wf/resume",
            json={"action": "approve"},
        )
        assert response.status_code == 400
        assert "not paused" in response.json()["detail"]

    def test_resume_invalid_action(self, client):
        _active_workflows["test-wf"] = {
            "status": "paused",
            "engine": None,
            "agents": {},
            "channel": None,
            "result": None,
            "paused_state": {},
        }
        response = client.post(
            "/workflows/test-wf/resume",
            json={"action": "maybe"},
        )
        assert response.status_code == 400
        assert "approve" in response.json()["detail"]
