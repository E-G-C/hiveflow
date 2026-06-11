"""Tests for API document upload and management endpoints."""

import json

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from hiveflow.api import _active_workflows, create_app
from hiveflow.core.config import HiveFlowConfig
from hiveflow.core.streaming import StreamChannel

# Valid minimal team config that passes TeamConfiguration validation
VALID_TEAM = {
    "team_name": "test",
    "description": "Test team for document upload",
    "agents": [
        {
            "id": "agent1",
            "role": "Test",
            "system_prompt": "You are a test agent.",
            "behavior_type": "llm_only",
        }
    ],
    "workflow": {"steps": [{"agent": "agent1", "type": "sequential"}]},
}


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


def _seed_workflow_with_docs(workflow_id: str = "test-wf-001") -> str:
    """Seed a workflow with pre-loaded documents."""
    _active_workflows[workflow_id] = {
        "status": "completed",
        "engine": None,
        "agents": {},
        "channel": StreamChannel(),
        "documents": [
            {
                "name": "report.txt",
                "format": "txt",
                "size_bytes": 100,
                "chunk_count": 2,
                "total_tokens_estimate": 30,
                "chunks": [
                    {"index": 0, "content": "Chunk one of the report."},
                    {"index": 1, "content": "Chunk two of the report."},
                ],
            },
            {
                "name": "data.csv",
                "format": "csv",
                "size_bytes": 50,
                "chunk_count": 1,
                "total_tokens_estimate": 10,
                "chunks": [
                    {"index": 0, "content": "col1,col2\na,b"},
                ],
            },
        ],
        "result": None,
    }
    return workflow_id


class TestStartWithDocuments:
    """Test POST /workflows/start with documents in JSON body."""

    def test_start_with_inline_documents(self, client) -> None:
        """JSON body documents are processed via the pipeline."""
        response = client.post("/workflows/start", json={
            "team": VALID_TEAM,
            "documents": [
                {"name": "inline.txt", "content": "Hello from inline."},
            ],
            "instructions": "Summarize the document.",
        })
        assert response.status_code == 200
        data = response.json()
        assert "workflow_id" in data
        assert data["status"] == "running"

    def test_start_without_documents(self, client) -> None:
        """Backward-compatible: start without documents works."""
        response = client.post("/workflows/start", json={
            "team": VALID_TEAM,
        })
        assert response.status_code == 200
        assert "workflow_id" in response.json()


class TestMultipartUpload:
    """Test POST /workflows/start/upload with multipart form data."""

    def test_multipart_upload_with_file(self, client) -> None:
        """Upload a file via multipart form data."""
        response = client.post(
            "/workflows/start/upload",
            data={
                "team": json.dumps(VALID_TEAM),
                "instructions": "Analyze the uploaded file.",
            },
            files=[
                ("documents", ("test.txt", b"File content here.", "text/plain")),
            ],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    def test_multipart_invalid_team_json(self, client) -> None:
        """Invalid team JSON returns 400."""
        response = client.post(
            "/workflows/start/upload",
            data={"team": "not valid json"},
        )
        assert response.status_code == 400


class TestUploadToWorkflow:
    """Test POST /workflows/{id}/documents."""

    def test_upload_to_existing_workflow(self, client) -> None:
        """Upload documents to an existing workflow."""
        wf_id = "upload-test-001"
        _active_workflows[wf_id] = {
            "status": "running",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "result": None,
        }
        response = client.post(
            f"/workflows/{wf_id}/documents",
            data={
                "inline_documents": json.dumps([
                    {"name": "added.txt", "content": "Newly added content."},
                ]),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["uploaded"] == 1
        assert data["total_documents"] == 1

    def test_upload_to_nonexistent_workflow(self, client) -> None:
        """Upload to nonexistent workflow returns 404."""
        response = client.post(
            "/workflows/nonexistent/documents",
            data={
                "inline_documents": json.dumps([
                    {"name": "x.txt", "content": "content"},
                ]),
            },
        )
        assert response.status_code == 404

    def test_upload_no_documents_provided(self, client) -> None:
        """Upload with no documents returns 400."""
        wf_id = "empty-upload"
        _active_workflows[wf_id] = {
            "status": "running",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "result": None,
        }
        response = client.post(f"/workflows/{wf_id}/documents")
        assert response.status_code == 400

    def test_upload_duplicate_name_rejected(self, client) -> None:
        """Duplicate document name returns 409."""
        wf_id = _seed_workflow_with_docs()
        response = client.post(
            f"/workflows/{wf_id}/documents",
            data={
                "inline_documents": json.dumps([
                    {"name": "report.txt", "content": "Duplicate!"},
                ]),
            },
        )
        assert response.status_code == 409


class TestListDocuments:
    """Test GET /workflows/{id}/documents."""

    def test_list_documents(self, client) -> None:
        """List all documents in a workflow."""
        wf_id = _seed_workflow_with_docs()
        response = client.get(f"/workflows/{wf_id}/documents")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        names = [d["name"] for d in data["documents"]]
        assert "report.txt" in names
        assert "data.csv" in names

    def test_list_documents_metadata_shape(self, client) -> None:
        """Each document has expected metadata fields."""
        wf_id = _seed_workflow_with_docs()
        response = client.get(f"/workflows/{wf_id}/documents")
        data = response.json()
        for doc in data["documents"]:
            assert "name" in doc
            assert "format" in doc
            assert "size_bytes" in doc
            assert "chunk_count" in doc
            assert "total_tokens_estimate" in doc

    def test_list_documents_empty(self, client) -> None:
        """Empty workflow returns empty list."""
        wf_id = "empty-wf"
        _active_workflows[wf_id] = {
            "status": "completed",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "result": {"status": "completed", "state": {}, "step_count": 0, "error": None},
        }
        response = client.get(f"/workflows/{wf_id}/documents")
        data = response.json()
        assert data["total"] == 0

    def test_list_documents_not_found(self, client) -> None:
        """Nonexistent workflow returns 404."""
        response = client.get("/workflows/nonexistent/documents")
        assert response.status_code == 404


class TestGetSpecificDocument:
    """Test GET /workflows/{id}/documents/{name}."""

    def test_get_document_by_name(self, client) -> None:
        """Get a specific document with chunks."""
        wf_id = _seed_workflow_with_docs()
        response = client.get(f"/workflows/{wf_id}/documents/report.txt")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "report.txt"
        assert "chunks" in data
        assert len(data["chunks"]) == 2

    def test_get_document_not_found(self, client) -> None:
        """Nonexistent document returns 404."""
        wf_id = _seed_workflow_with_docs()
        response = client.get(f"/workflows/{wf_id}/documents/missing.txt")
        assert response.status_code == 404

    def test_get_document_workflow_not_found(self, client) -> None:
        """Nonexistent workflow returns 404."""
        response = client.get("/workflows/nope/documents/anything.txt")
        assert response.status_code == 404
