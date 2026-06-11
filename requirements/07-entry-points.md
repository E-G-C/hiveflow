[< Back to Index](README.md)

---

## Entry Points: Embedded, CLI, and API

The framework is consumed through its **public Python API** (`HiveFlow` class).
All other consumption modes — CLI, REST API, native apps — are thin wrappers
that delegate to this API. See
[Core Architecture — Public API](01-core-architecture.md#4-public-api-design-principles)
for the design principles.

### Python Package Interface (Primary)

The embedded Python API is the native way to use the framework. All other
entry points delegate to it.

```python
from hiveflow import HiveFlow

hf = HiveFlow()

# --- Discovery ---

# List available templates and archetypes
templates = hf.team_library().list_templates()
archetypes = hf.archetype_library().list_archetypes()
tools = hf.tool_registry().list_ids()
models = hf.model_registry().list_ids()

# --- Execution ---

# Run from a template (async)
session = await hf.run(
    team="research_report",
    task="Impact of AI on healthcare",
)
print(session.result.state)

# Run from a template (sync wrapper for scripts and desktop apps)
session = hf.run_sync(
    team="research_report",
    task="Impact of AI on healthcare",
)

# Run with a custom team config
from hiveflow.core.schema import TeamConfiguration
config = TeamConfiguration.from_json_file("./my-team.json")
session = await hf.run(team=config, task="...")

# Run with documents
session = await hf.run(
    team="contract_review",
    task="Review this contract for risks",
    documents=["./contract.pdf"],
)

# --- Human-in-the-loop ---

session = await hf.run(team="deploy_pipeline", task='{"service": "api-v2"}')

if session.status == WorkflowStatus.PAUSED:
    # Inspect what the workflow needs
    for req in session.pending_requests:
        print(f"Agent {req.agent_id} asks: {req.context}")

    # Respond and resume via HiveFlow facade
    session = await hf.resume(
        session_id=session.session_id,
        responses={
            req.request_id: "approved"
            for req in session.pending_requests
        },
    )

# --- Event streaming ---

session = await hf.run(team="research_report", task="...")
consumer = session.subscribe()
async for event in consumer:
    if event.event_type == StreamEventType.STEP_END:
        print(f"Agent {event.agent_id} finished")
    elif event.event_type == StreamEventType.OUTPUT:
        print(event.data)

# --- LLM team generation ---

result = await hf.generate_team(
    task="Legal contract review workflow",
    auto_approve=False,
)
# Inspect the proposed team (config is a dict)
print(result.config["team_name"])
print(result.capability_gaps)
# Save for reuse — wrap in TeamConfiguration to use save_json()
from hiveflow.core.schema import TeamConfiguration
team_config = TeamConfiguration(**result.config)
team_config.save_json("./teams/legal_review.json")
# New archetypes invented by the LLM (list of dicts)
for arch in result.new_archetypes:
    print(arch)
```

### CLI Interface

The CLI wraps the Python API for terminal-based usage. It is an optional
package, not part of the core framework.

```bash
# --- Execution ---

# Run a workflow from a template
hiveflow run --template research_report --instructions "Impact of AI on healthcare"

# Run with a custom team config file
hiveflow run --template ./my-team.json --instructions "..."

# Run with documents
hiveflow run --template contract_review --instructions "Review for risks" --doc ./contract.pdf

# --- Discovery (planned) ---

# List available templates
hiveflow templates list

# List available archetypes
hiveflow archetypes list

# List installed tool plugins
hiveflow tools list

# List installed LLM providers
hiveflow providers list

# --- Team management (planned) ---

# Generate a team config from a description
hiveflow templates generate --task "Code review team for Python projects"

# Validate a team config
hiveflow templates validate ./my-team.json

# --- Workflow control (planned) ---

# Resume a paused workflow (from checkpoint)
hiveflow resume --checkpoint <checkpoint_id> --response "approved"

# Dry-run an action-oriented workflow (no side effects)
hiveflow run --template deploy_pipeline --instructions '{"service": "api-v2"}' --dry-run
```

The CLI is installed as a console script entry point:

```toml
[project.scripts]
hiveflow = "hiveflow.cli.main:main"
```

### REST API (Reference Implementation)

A reference FastAPI server is provided as an optional package
(`hiveflow-api`). It wraps the `HiveFlow` public API, exposing all operations
as HTTP endpoints. This is not part of the core framework — it is one possible
consumer.

```
# --- Workflow execution ---
POST   /workflows/start                     # Start a workflow (team + task)
POST   /workflows/start/upload              # Start with multipart file uploads
GET    /workflows/{workflow_id}              # Get session status and result
GET    /workflows                            # List all workflow executions
POST   /workflows/{workflow_id}/resume       # Resume a paused workflow
DELETE /workflows/{workflow_id}              # Cancel a running workflow (planned)

# --- Event streaming ---
WS     /ws/workflows/{workflow_id}           # WebSocket for real-time events
GET    /workflows/{workflow_id}/events       # SSE fallback (planned)

# --- Discovery ---
GET    /templates                            # List available team templates
GET    /templates/{name}                     # Get a specific team config
GET    /tools                                # List registered tool plugins
GET    /archetypes                           # List available archetypes (planned)
GET    /models                               # List available models (planned)

# --- Team management ---
POST   /teams/validate                       # Validate a team configuration
POST   /templates/generate                   # LLM-generate a team from description

# --- Document management ---
POST   /workflows/{workflow_id}/documents    # Upload documents to workflow
GET    /workflows/{workflow_id}/documents    # List workflow documents
GET    /workflows/{workflow_id}/documents/{name} # Get a specific document

# --- Checkpoints (planned) ---
GET    /checkpoints                          # List saved checkpoints
GET    /checkpoints/{id}                     # Get checkpoint details

# --- Actions (planned, for action_executor workflows) ---
GET    /workflows/{workflow_id}/actions      # List actions taken in a run
POST   /actions/{id}/rollback                # Rollback a specific action
```

#### Approval Flow via REST

The canonical human-in-the-loop flow for a web application:

```
1. POST /workflows/start           → 200 { workflow_id: "abc", status: "running" }
2. GET  /workflows/abc             → 200 { status: "paused", result: {...} }
3. (Frontend shows approval UI to the user)
4. POST /workflows/abc/resume       { action: "approve", feedback: "..." }
5. GET  /workflows/abc             → 200 { status: "completed", result: {...} }
```

For real-time updates, the frontend connects to the WebSocket endpoint
(`/ws/workflows/{workflow_id}`) and receives `StreamEvent` objects as
they happen.

#### Stateless Scaling

Because the `HiveFlow` instance is stateless and all workflow state lives in
`WorkflowSession` objects backed by checkpoint storage, the REST API can be
horizontally scaled behind a load balancer. Any server instance can resume
any session if they share the same checkpoint storage backend.

### Native Application Integration

For desktop or native applications (e.g., a Windows app), the framework is
used via the embedded Python API with the sync wrapper:

```python
# Native app integration pattern
hf = HiveFlow()

# Sync execution (blocks the calling thread)
session = hf.run_sync(team="research_report", task=user_input)

# Handle approval via native UI dialog
if session.status == WorkflowStatus.PAUSED:
    # Show a dialog to the user
    user_response = show_approval_dialog(session.pending_requests)
    # Resume is async — wrap in asyncio.run or use a thread
    import asyncio
    session = asyncio.run(
        hf.resume(session.session_id, responses=user_response)
    )

# Use the result
display_result(session.result)
```

For non-blocking execution in a UI thread, the async API can be run on a
background thread or integrated with the application's event loop.

### Docker

```dockerfile
FROM python:3.12-slim
RUN pip install hiveflow hiveflow-api hiveflow-llm-openai
CMD ["hiveflow", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Cloud & Remote Document Sources

Beyond URLs and local files, the framework supports **cloud storage and
enterprise document repositories** as first-class source plugins.

### Source Plugin Interface

```
 SourcePlugin (protocol / base class)
├── source_id: str                          # e.g. "azure_blob", "s3", "sharepoint"
├── description: str                        # human-readable description
├── list_documents(path, filters) -> list[DocumentRef]  # enumerate available docs
├── fetch(doc_ref) -> bytes | str           # retrieve document content
├── supports_streaming: bool                # large file streaming support
└── manifest.yaml                           # metadata, dependencies, config
```

### Built-in Source Plugins

| Source         | Package                    | Backend                 | Notes                             |
| -------------- | -------------------------- | ----------------------- | --------------------------------- |
| **Azure Blob** | `hiveflow-src-azure-blob`  | Azure Blob Storage      | Container/blob path addressing    |
| **AWS S3**     | `hiveflow-src-s3`          | Amazon S3               | Bucket/key addressing             |
| **GCS**        | `hiveflow-src-gcs`         | Google Cloud Storage    | Bucket/object addressing          |
| **SharePoint** | `hiveflow-src-sharepoint`  | SharePoint Online       | Site/library/folder addressing    |
| **Google Drive** | `hiveflow-src-gdrive`    | Google Drive API        | Folder ID / search-based access   |
| **OneDrive**   | `hiveflow-src-onedrive`    | Microsoft Graph API     | Path or item ID addressing        |
| **Confluence** | `hiveflow-src-confluence`  | Atlassian Confluence    | Space/page tree enumeration       |
| **Notion**     | `hiveflow-src-notion`      | Notion API              | Database/page access              |

### Integration with Document Loaders

```
Source Plugin (fetch) → Format Detection → Document Loader → Chunking → Embedding → Vector Store
```

### Configuration

```json
{
  "sources": [
    {
      "type": "azure_blob",
      "container": "research-docs",
      "connection_string_env": "AZURE_STORAGE_CONNECTION_STRING",
      "path_prefix": "reports/2024/"
    },
    {
      "type": "sharepoint",
      "site": "https://company.sharepoint.com/sites/research",
      "library": "Documents",
      "auth_env": "SHAREPOINT_TOKEN"
    }
  ]
}
```

---

---

[Next: Output Pipeline >](08-output-pipeline.md)
