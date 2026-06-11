# REST API Contract: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18

## Modified Endpoints

### `POST /workflows/start` — Extended

Accepts multipart form data in addition to the existing JSON body.

**Content-Type**: `multipart/form-data` or `application/json`

#### Multipart Form Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template` | `str` | Yes | Team template name |
| `instructions` | `str` | No | Task instructions |
| `instructions_file` | `UploadFile` | No | Instructions as uploaded file |
| `documents` | `UploadFile` (repeatable) | No | Document files |

#### JSON Body (existing, extended)

```json
{
  "template": "content_rewriter",
  "instructions": "Rewrite as a blog post",
  "documents": [
    {"name": "transcript.txt", "content": "Hello everyone..."}
  ]
}
```

#### Response (unchanged shape, extended)

```json
{
  "workflow_id": "wf_abc123",
  "status": "running",
  "documents_loaded": 1,
  "document_summary": "1 document loaded: transcript.txt (2 chunks, ~6100 tokens)"
}
```

---

## New Endpoints

### `POST /workflows/{workflow_id}/documents`

Upload documents to a running (paused) workflow.

**Content-Type**: `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `documents` | `UploadFile` (repeatable) | Yes | Document files to add |

**Response** (201 Created):

```json
{
  "added": [
    {
      "name": "report.pdf",
      "format": "pdf",
      "size_bytes": 145000,
      "chunk_count": 12,
      "total_tokens_estimate": 18200
    }
  ],
  "total_documents": 3,
  "document_summary": "3 documents loaded: ..."
}
```

**Errors**:
- `404` — Workflow not found
- `409` — Workflow not in a state that accepts new documents
- `413` — Total document size would exceed limit
- `422` — Unsupported format or validation error

---

### `GET /workflows/{workflow_id}/documents`

List all documents loaded in a workflow.

**Response** (200 OK):

```json
{
  "documents": [
    {
      "name": "transcript.txt",
      "format": "txt",
      "size_bytes": 24500,
      "chunk_count": 4,
      "total_tokens_estimate": 6100
    },
    {
      "name": "notes.md",
      "format": "md",
      "size_bytes": 3200,
      "chunk_count": 1,
      "total_tokens_estimate": 800
    }
  ],
  "total_documents": 2,
  "total_size_bytes": 27700,
  "total_tokens_estimate": 6900
}
```

**Errors**:
- `404` — Workflow not found

---

### `GET /workflows/{workflow_id}/documents/{name}`

Get a specific document's content and chunks.

**Path parameter**: `name` — URL-encoded document name (e.g.,
`reports%2Fsummary.txt` for `reports/summary.txt`)

**Response** (200 OK):

```json
{
  "name": "transcript.txt",
  "format": "txt",
  "size_bytes": 24500,
  "chunks": [
    {"index": 0, "content": "Hello everyone, welcome..."},
    {"index": 1, "content": "...the key insight is..."}
  ],
  "chunk_count": 2,
  "total_tokens_estimate": 6100
}
```

**Errors**:
- `404` — Workflow or document not found

---

## Upload Constraints

| Constraint | Value | Configurable |
|-----------|-------|-------------|
| Max total document size | 50 MB | Yes (`max_document_bytes`) |
| Max single file upload | 50 MB | Yes (same limit) |
| Allowed file types | `.txt`, `.csv`, `.tsv`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.json`, `.xml` | Via registered loaders |
| Upload directory | System temp / configurable | Yes |
| Path traversal | Rejected (API uploads go to temp dir) | N/A |
