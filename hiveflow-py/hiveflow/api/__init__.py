"""FastAPI Backend API Layer - REST/WebSocket API for HiveFlow.

Provides endpoints for:
- Team configuration management (CRUD)
- Workflow execution (start, status, cancel)
- Document upload and management
- Real-time streaming via WebSocket
"""

import asyncio
import hmac
import json
import tempfile
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.config import HiveFlowConfig, get_config
from hiveflow.core.streaming import StreamChannel, StreamConsumer, StreamEvent, StreamEventType

logger = structlog.get_logger()

# In-memory store for active workflows (production would use a database)
_active_workflows: dict[str, dict[str, Any]] = {}

# Track background tasks to prevent garbage collection and enable cleanup
_background_tasks: set[asyncio.Task[None]] = set()


def create_app(config: HiveFlowConfig | None = None) -> Any:
    """Create and configure the FastAPI application.

    Args:
        config: Optional HiveFlowConfig override

    Returns:
        FastAPI application instance
    """
    try:
        from fastapi import (
            FastAPI,
            File,
            Form,
            HTTPException,
            UploadFile,
            WebSocket,
            WebSocketDisconnect,
        )
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:
        raise ImportError("FastAPI required. Install with: uv add 'hiveflow[api]'") from exc

    app_config = config or get_config()
    app = FastAPI(
        title="HiveFlow API",
        description="Multi-agent workflow orchestration API",
        version="0.1.0",
    )

    # CORS: use configured origins; enforce no credentials with wildcard origins
    cors_origins = [o.strip() for o in app_config.CORS_ORIGINS.split(",") if o.strip()]
    allow_credentials = app_config.CORS_ALLOW_CREDENTIALS
    if cors_origins == ["*"]:
        allow_credentials = False  # wildcard + credentials violates CORS spec

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- API Key Authentication Middleware ---
    _api_key = app_config.API_KEY
    _api_key_header = app_config.API_KEY_HEADER
    _PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    if _api_key:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        class APIKeyMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):  # noqa: ANN001
                if request.url.path in _PUBLIC_PATHS:
                    return await call_next(request)
                # Skip WebSocket connections (handled separately if needed)
                if request.scope.get("type") == "websocket":
                    return await call_next(request)
                key = request.headers.get(_api_key_header, "")
                # Constant-time comparison to avoid leaking the key via timing.
                if not hmac.compare_digest(key, _api_key):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid or missing API key"},
                    )
                return await call_next(request)

        app.add_middleware(APIKeyMiddleware)

    # -- Rate Limiting Middleware ---
    _rate_limit_rpm = app_config.API_RATE_LIMIT_RPM

    if _rate_limit_rpm > 0:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        _rate_buckets: dict[str, list[float]] = defaultdict(list)

        class RateLimitMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):  # noqa: ANN001
                if request.url.path in _PUBLIC_PATHS:
                    return await call_next(request)
                client_ip = request.client.host if request.client else "unknown"
                now = time.monotonic()
                window = 60.0  # 1 minute
                # Prune expired entries
                recent = [t for t in _rate_buckets[client_ip] if now - t < window]
                if len(recent) >= _rate_limit_rpm:
                    _rate_buckets[client_ip] = recent
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded"},
                    )
                recent.append(now)
                # Evict empty buckets so the IP keyspace cannot grow unbounded.
                if recent:
                    _rate_buckets[client_ip] = recent
                else:
                    _rate_buckets.pop(client_ip, None)
                return await call_next(request)

        app.add_middleware(RateLimitMiddleware)

    # -- Health ---

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # -- Configuration ---

    # Config fields that must never be exposed over the API.
    _SENSITIVE_CONFIG_FIELDS = {"API_KEY"}

    @app.get("/config")
    async def get_current_config() -> dict[str, Any]:
        data = app_config.model_dump()
        for field in _SENSITIVE_CONFIG_FIELDS:
            if data.get(field):
                data[field] = "***redacted***"
        return data

    # -- Team Management ---

    @app.post("/teams/validate")
    async def validate_team(team_json: dict[str, Any]) -> dict[str, Any]:
        """Validate a team configuration without executing it."""
        from hiveflow.core.schema import TeamConfiguration

        try:
            team = TeamConfiguration(**team_json)
            return {
                "valid": True,
                "agents": len(team.agents),
                "workflow_steps": len(team.workflow.steps) if team.workflow else 0,
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # -- Templates ---

    @app.get("/templates")
    async def list_templates() -> dict[str, Any]:
        """List all available team templates."""
        from hiveflow.core.teams import TeamTemplateLibrary

        lib = TeamTemplateLibrary.default()
        templates = []
        for name in lib.list_templates():
            tpl = lib.get(name)
            templates.append(
                {
                    "name": name,
                    "description": tpl.get("description", "") if tpl else "",
                    "agent_count": len(tpl.get("agents", [])) if tpl else 0,
                }
            )
        return {"templates": templates}

    @app.get("/templates/{name}")
    async def get_template(name: str) -> dict[str, Any]:
        """Get a specific template by name."""
        from hiveflow.core.teams import TeamTemplateLibrary

        lib = TeamTemplateLibrary.default()
        tpl = lib.get(name)
        if tpl is None:
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        return tpl

    @app.post("/templates/generate")
    async def generate_template(request: dict[str, Any]) -> dict[str, Any]:
        """Generate a team configuration from a task description."""
        from hiveflow.core.teams import TeamGenerator

        task = request.get("task_description", "")
        if not task:
            raise HTTPException(status_code=400, detail="Missing 'task_description'")
        agent_types = request.get("agent_types")
        include_review = request.get("include_review", True)
        generator = TeamGenerator()
        return generator.generate_team(task, agent_types=agent_types, include_review=include_review)

    # -- Tools ---

    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        """List all registered tool plugins."""
        from hiveflow.plugins.tools import ToolRegistry

        registry = ToolRegistry(drop_in_dir=None)
        registry.discover()
        tools = []
        for tool_id in registry.list_ids():
            tool = registry.get(tool_id)
            if tool:
                tools.append(
                    {
                        "id": tool.plugin_id,
                        "description": tool.description,
                    }
                )
        return {"tools": tools}

    # -- Workflow Execution ---

    @app.post("/workflows/start")
    async def start_workflow(request: dict[str, Any]) -> dict[str, Any]:
        """Start a new workflow execution.

        Request body:
            team: Team configuration dict
            initial_state: Initial workflow state
            documents: Optional list of inline document dicts
            instructions: Optional instructions string
            instructions_file: Optional path to instructions file
        """
        from hiveflow.core.agent import Agent
        from hiveflow.core.schema import TeamConfiguration
        from hiveflow.core.workflow import WorkflowEngine
        from hiveflow.plugins.llm import LLMProviderRegistry

        team_data = request.get("team")
        raw_state = request.get("initial_state", {})
        # Strip internal keys (prefixed with '_') from user-supplied state
        initial_state = (
            {k: v for k, v in raw_state.items() if not k.startswith("_")}
            if isinstance(raw_state, dict)
            else {}
        )
        doc_inputs = request.get("documents")
        instructions = request.get("instructions")
        instructions_file = request.get("instructions_file")

        if not team_data:
            raise HTTPException(status_code=400, detail="Missing 'team' in request body")

        try:
            team = TeamConfiguration(**team_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid team config: {e}") from e

        workflow_id = str(uuid.uuid4())

        # Build agents from team config
        llm_registry = LLMProviderRegistry(drop_in_dir=None)
        llm_registry.discover()

        agents: dict[str, Agent] = {}
        for agent_def in team.agents:
            model_ref = app_config.resolve_model(agent_def.model)
            try:
                provider, _model_name = llm_registry.resolve_model(model_ref)
            except (KeyError, ValueError):
                provider = None

            agents[agent_def.id] = Agent.from_definition(
                agent_def,
                llm_provider=provider,
                tools=[],
                resolved_model=model_ref,
            )

        # Process documents if provided
        if doc_inputs:
            try:
                documents, doc_summary = await _load_documents(doc_inputs)
                initial_state["documents"] = documents
                initial_state["document_summary"] = doc_summary
            except (ValueError, FileNotFoundError) as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

        # Process instructions
        if instructions:
            initial_state["task"] = instructions
        elif instructions_file:
            # Reading server-side file paths supplied by an API client is a
            # local-file-inclusion risk. Instructions must be sent inline (or
            # uploaded as a document); server-side paths are only honored by
            # embedded/CLI callers.
            raise HTTPException(
                status_code=400,
                detail="'instructions_file' is not allowed over the API; "
                "send 'instructions' inline or upload the file as a document.",
            )

        # Build workflow engine
        engine = WorkflowEngine.from_schema(team.workflow)
        channel = StreamChannel()

        # Store workflow state
        _active_workflows[workflow_id] = {
            "status": "running",
            "engine": engine,
            "agents": agents,
            "channel": channel,
            "result": None,
        }

        # Register engine events to stream channel
        def on_engine_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return  # No running loop — drop the event rather than crash
            event_task = loop.create_task(
                channel.publish(
                    StreamEvent(
                        event_type=StreamEventType(event_type),
                        agent_id=agent_id,
                        data=data,
                    )
                )
            )
            # Retain a reference so the task is not garbage-collected mid-flight.
            _background_tasks.add(event_task)
            event_task.add_done_callback(_background_tasks.discard)

        engine.on_event(on_engine_event)

        # Execute workflow in background
        async def run_workflow() -> None:
            try:
                from hiveflow.core.workflow import WorkflowStatus

                result = await engine.execute(agents, initial_state)
                _active_workflows[workflow_id]["status"] = result.status.value
                _active_workflows[workflow_id]["result"] = {
                    "status": result.status.value,
                    "state": result.state,
                    "step_count": len(result.step_results),
                    "error": result.error,
                }
                # Save state for paused workflows so they can be resumed
                if result.status == WorkflowStatus.PAUSED:
                    _active_workflows[workflow_id]["paused_state"] = result.state
            except Exception as e:
                logger.exception("Workflow %s failed", workflow_id)
                _active_workflows[workflow_id]["status"] = "failed"
                _active_workflows[workflow_id]["result"] = {"error": str(e)}
            finally:
                await channel.close()

        task = asyncio.create_task(run_workflow())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return {"workflow_id": workflow_id, "status": "running"}

    @app.get("/workflows/{workflow_id}")
    async def get_workflow_status(workflow_id: str) -> dict[str, Any]:
        """Get workflow execution status."""
        wf = _active_workflows.get(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")

        response: dict[str, Any] = {
            "id": workflow_id,
            "workflow_id": workflow_id,
            "status": wf["status"],
        }
        if wf["result"]:
            response["result"] = wf["result"]
        return response

    @app.get("/workflows")
    async def list_workflows() -> dict[str, Any]:
        """List all workflow executions."""
        return {
            "workflows": [
                {"id": wid, "workflow_id": wid, "status": wf["status"]}
                for wid, wf in _active_workflows.items()
            ]
        }

    # -- Workflow Resume (Human Gate) ---

    @app.post("/workflows/{workflow_id}/resume")
    async def resume_workflow(workflow_id: str, request: dict[str, Any]) -> dict[str, Any]:
        """Resume a paused workflow after human gate decision."""
        wf = _active_workflows.get(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if wf["status"] != "paused":
            raise HTTPException(status_code=400, detail="Workflow is not paused")

        action = request.get("action")
        feedback = request.get("feedback", "")

        if action not in ("approve", "reject"):
            raise HTTPException(
                status_code=400,
                detail="action must be 'approve' or 'reject'",
            )

        state = dict(wf.get("paused_state", {}))
        state.pop("awaiting_human_input", None)

        if action == "approve":
            state["human_approved"] = True
            state["human_input"] = feedback or "Approved"
        else:
            state["human_rejected"] = True
            state["human_input"] = feedback or "Rejected"

        engine = wf["engine"]
        agents = wf["agents"]
        channel = wf["channel"]
        wf["status"] = "running"

        async def continue_workflow() -> None:
            try:
                from hiveflow.core.workflow import WorkflowStatus

                result = await engine.execute(agents, state)
                wf["status"] = result.status.value
                wf["result"] = {
                    "status": result.status.value,
                    "state": result.state,
                    "step_count": len(result.step_results),
                    "error": result.error,
                }
                if result.status == WorkflowStatus.PAUSED:
                    wf["paused_state"] = result.state
            except Exception as e:
                logger.exception("Workflow %s failed on resume", workflow_id)
                wf["status"] = "failed"
                wf["result"] = {"error": str(e)}
            finally:
                await channel.close()

        task = asyncio.create_task(continue_workflow())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {"workflow_id": workflow_id, "status": "running"}

    # -- Document Upload (Multipart) ---

    @app.post("/workflows/start/upload")
    async def start_workflow_with_upload(
        team: str = Form(...),
        instructions: str | None = Form(None),
        documents: list[UploadFile] = File(None),
    ) -> dict[str, Any]:
        """Start a workflow with multipart document upload.

        Form fields:
            team: JSON string of team configuration
            instructions: Optional instructions text
            documents: Optional file uploads
        """
        try:
            team_data = json.loads(team)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in 'team' field: {e}") from e

        # Convert uploaded files to inline document dicts
        doc_inputs: list[dict[str, str]] = []
        _max_upload_bytes = app_config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if documents:
            for upload_file in documents:
                content = await upload_file.read()
                if len(content) > _max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{upload_file.filename}' exceeds "
                        f"{app_config.MAX_UPLOAD_SIZE_MB} MB limit",
                    )
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = content.decode("latin-1")
                doc_inputs.append(
                    {
                        "name": Path(upload_file.filename or "upload.txt").name,
                        "content": text,
                    }
                )

        # Delegate to the JSON start endpoint logic
        request_body: dict[str, Any] = {
            "team": team_data,
            "initial_state": {},
        }
        if doc_inputs:
            request_body["documents"] = doc_inputs
        if instructions:
            request_body["instructions"] = instructions

        return await start_workflow(request_body)

    # -- Workflow Document Management ---

    @app.post("/workflows/{workflow_id}/documents")
    async def upload_workflow_documents(
        workflow_id: str,
        documents: list[UploadFile] = File(None),
        inline_documents: str | None = Form(None),
    ) -> dict[str, Any]:
        """Upload documents to a running workflow.

        Accepts multipart file uploads and/or inline document JSON.
        """
        wf = _active_workflows.get(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")

        doc_inputs: list[dict[str, str]] = []

        # Process file uploads
        _max_upload_bytes = app_config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if documents:
            for upload_file in documents:
                content = await upload_file.read()
                if len(content) > _max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{upload_file.filename}' exceeds "
                        f"{app_config.MAX_UPLOAD_SIZE_MB} MB limit",
                    )
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = content.decode("latin-1")
                doc_inputs.append(
                    {
                        "name": Path(upload_file.filename or "upload.txt").name,
                        "content": text,
                    }
                )

        # Process inline JSON documents
        if inline_documents:
            try:
                inline_list = json.loads(inline_documents)
                if isinstance(inline_list, list):
                    doc_inputs.extend(inline_list)
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid JSON in 'inline_documents': {e}",
                ) from e

        if not doc_inputs:
            raise HTTPException(
                status_code=400,
                detail="No documents provided. Upload files or include inline_documents.",
            )

        try:
            new_docs, doc_summary = await _load_documents(doc_inputs)
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # Merge into workflow state
        existing_docs = _get_workflow_documents(wf)

        # Check for duplicate names
        existing_names = {d.get("name") for d in existing_docs}
        for doc in new_docs:
            if doc.get("name") in existing_names:
                raise HTTPException(
                    status_code=409,
                    detail=f"Document '{doc.get('name')}' already exists in workflow.",
                )

        existing_docs.extend(new_docs)
        wf["documents"] = existing_docs

        return {
            "uploaded": len(new_docs),
            "total_documents": len(existing_docs),
            "documents": [
                {
                    "name": d.get("name"),
                    "format": d.get("format"),
                    "chunk_count": d.get("chunk_count", 0),
                }
                for d in new_docs
            ],
        }

    @app.get("/workflows/{workflow_id}/documents")
    async def list_workflow_documents(workflow_id: str) -> dict[str, Any]:
        """List all documents loaded in a workflow."""
        wf = _active_workflows.get(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")

        documents = _get_workflow_documents(wf)

        return {
            "workflow_id": workflow_id,
            "documents": [
                {
                    "name": d.get("name"),
                    "format": d.get("format"),
                    "size_bytes": d.get("size_bytes", 0),
                    "chunk_count": d.get("chunk_count", 0),
                    "total_tokens_estimate": d.get("total_tokens_estimate", 0),
                }
                for d in documents
            ],
            "total": len(documents),
        }

    @app.get("/workflows/{workflow_id}/documents/{document_name}")
    async def get_workflow_document(workflow_id: str, document_name: str) -> dict[str, Any]:
        """Get a specific document by name with its chunks."""
        wf = _active_workflows.get(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")

        documents = _get_workflow_documents(wf)
        doc = next((d for d in documents if d.get("name") == document_name), None)

        if doc is None:
            raise HTTPException(
                status_code=404,
                detail=f"Document '{document_name}' not found in workflow.",
            )

        return doc

    def _get_workflow_documents(wf: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract documents from workflow state."""
        # Check directly stored documents first (from POST upload)
        if "documents" in wf and wf["documents"]:
            return wf["documents"]

        # Fall back to result state
        result = wf.get("result")
        if result and isinstance(result.get("state"), dict):
            return result["state"].get("documents", [])

        # Check paused state
        paused = wf.get("paused_state")
        if paused and isinstance(paused, dict):
            return paused.get("documents", [])

        return []

    # -- Demo Seed ---

    @app.post("/demo/seed")
    async def seed_demo_data() -> dict[str, Any]:
        """Seed demo workflow data for UI development/testing."""
        _active_workflows.clear()

        # --- Workflow 1: completed research workflow ---
        wf1_id = "demo-research-001"
        _active_workflows[wf1_id] = {
            "status": "completed",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "result": {
                "status": "completed",
                "state": {
                    "task": "Research the impact of AI on healthcare",
                    "research_notes": "AI is transforming healthcare through improved diagnostics, "
                    "drug discovery, and personalized medicine...",
                    "draft": "# AI in Healthcare\n\nArtificial intelligence is revolutionizing "
                    "healthcare delivery across multiple domains...",
                    "review_feedback": "Well-structured report. Consider adding more citations.",
                    "final_output": "# AI in Healthcare - Final Report\n\n"
                    "## Executive Summary\n"
                    "AI is transforming healthcare through three key areas: "
                    "diagnostics, drug discovery, and personalized treatment plans.\n\n"
                    "## Key Findings\n"
                    "1. AI diagnostics achieve 94% accuracy in radiology...\n"
                    "2. Drug discovery timelines reduced by 60%...\n"
                    "3. Personalized treatment improves outcomes by 35%...",
                },
                "step_count": 3,
                "error": None,
            },
        }

        # --- Workflow 2: running workflow ---
        wf2_id = "demo-analysis-002"
        _active_workflows[wf2_id] = {
            "status": "running",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "result": None,
        }

        # --- Workflow 3: paused (human gate) ---
        wf3_id = "demo-publish-003"
        _active_workflows[wf3_id] = {
            "status": "paused",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "paused_state": {
                "task": "Write and publish a blog post about quantum computing",
                "draft": "# Quantum Computing in 2025\n\nQuantum computing has reached...",
                "edited_draft": "# Quantum Computing in 2025\n\n(Edited) Quantum computing...",
                "awaiting_human_input": True,
                "human_gate_prompt": "The blog post is ready for publishing. Please review and approve.",
            },
            "result": None,
        }

        # --- Workflow 4: failed workflow ---
        wf4_id = "demo-failed-004"
        _active_workflows[wf4_id] = {
            "status": "failed",
            "engine": None,
            "agents": {},
            "channel": StreamChannel(),
            "result": {
                "status": "failed",
                "state": {"task": "Generate unit tests for legacy codebase"},
                "step_count": 1,
                "error": "Tool execution failed: FileNotFoundError - /src/legacy/main.py not found",
            },
        }

        return {
            "seeded": True,
            "workflows": [
                {"id": wf1_id, "status": "completed"},
                {"id": wf2_id, "status": "running"},
                {"id": wf3_id, "status": "paused"},
                {"id": wf4_id, "status": "failed"},
            ],
        }

    # -- WebSocket Streaming ---

    @app.websocket("/ws/workflows/{workflow_id}")
    async def workflow_stream(websocket: WebSocket, workflow_id: str) -> None:
        """WebSocket endpoint for real-time workflow events."""
        wf = _active_workflows.get(workflow_id)
        if not wf:
            await websocket.close(code=4004, reason="Workflow not found")
            return

        await websocket.accept()
        channel: StreamChannel = wf["channel"]
        consumer = channel.subscribe()

        try:
            async for event in consumer:
                await websocket.send_json(event.to_dict())
        except WebSocketDisconnect:
            pass
        finally:
            await consumer.close()

    return app


async def _load_documents(
    doc_inputs: list[dict[str, str] | str],
) -> tuple[list[dict[str, Any]], str]:
    """Load documents through the pipeline from inline dicts.

    Args:
        doc_inputs: List of inline document dicts with 'name' and 'content'

    Returns:
        Tuple of (documents state list, summary string)
    """
    from hiveflow.core.documents import DocumentPipeline

    pipeline = DocumentPipeline()
    return await pipeline.load(doc_inputs)
