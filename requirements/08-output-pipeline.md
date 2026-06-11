[< Back to Index](README.md)

---

# Output Pipeline

This document covers the complete output lifecycle: how workflows select their
deliverable type, how text style is controlled, how the result payload is
structured, and how it gets exported to various formats.

> **Consolidated from:** Former `08-output-and-content.md` (Output Type Routing,
> Tone & Style) and `11-output-and-frontend.md` (Publisher Pipeline, Layout
> Templates). Source Mode was relocated to
> [05-data-processing.md](05-data-processing.md) as it is an input concern.

---

## 1. Output Type Routing

Different output types require different **agent pipelines, prompt strategies,
and structural templates**. The framework routes workflows based on the
requested output type — generalizing beyond "report types" to any deliverable.

### Built-in Output Types

| Output Type            | Pipeline shape                                                    | Description                                       |
| ---------------------- | ----------------------------------------------------------------- | ------------------------------------------------- |
| **detailed_report**    | Multi-agent: decompose → collect → evaluate → produce → emit     | Long-form report with sections; citations optional |
| **quick_report**       | Minimal: collect → produce                                        | Short summary; 1–2 pages                          |
| **outline**            | Minimal: collect                                                  | Bullet-point outline with sources                 |
| **resource_list**      | Minimal: collect                                                  | Curated list of sources with summaries            |
| **deep_research**      | Recursive multi-level                                             | Exhaustive multi-branch exploration               |
| **decision_record**    | Multi-agent: decompose → collect → evaluate → produce             | Structured decision with evidence                 |
| **action_plan**        | Multi-agent: decompose → collect → evaluate                       | Step-by-step executable plan                      |
| **code_artifact**      | Multi-agent: produce → evaluate → iterate → emit                  | Generated and tested code                         |
| **incident_report**    | Multi-agent: collect → produce → evaluate → emit                  | Post-mortem with timeline and RCA                 |
| **custom**             | User-defined pipeline                                             | Fully custom team config                          |

### Per-Type Prompt Templates

Each output type maps to a **prompt template set** governing agent behavior:

- **Query generation prompts** — How sub-queries are derived from the main topic
- **Writing prompts** — Structure, length, and style instructions
- **Review prompts** — Quality criteria to check against
- **Action prompts** — Guidelines for what actions to take and when
- **Introduction / conclusion prompts** — Opening and closing section generation

### Routing Logic

```python
# Pseudocode
def route_output(output_type: str, instructions: str, config: dict) -> TeamConfig:
    if output_type in template_library:
        team_config = template_library.load(output_type)
    elif output_type == "custom":
        team_config = config["custom_team"]
    else:
        # Fallback: ask LLM to generate a team config
        team_config = await generate_team_config(output_type, instructions)

    # Apply per-type prompt overrides
    team_config.prompts = prompt_library.get_set(output_type)
    return team_config
```

### Configuration

```json
{
  "output_type": "detailed_report",
  "output_options": {
    "max_sections": 8,
    "words_per_section": 800,
    "include_introduction": true,
    "include_conclusion": true,
    "include_table_of_contents": true
  },
  "citations": {
    "enabled": true,
    "style": "apa",
    "inline": true,
    "generate_reference_section": true
  }
}
```

---

## 2. Tone & Style System

Many workflows produce text-based outputs (reports, summaries, recommendations,
post-mortems, decision records). The **tone** of that output matters — a
research report for an academic audience reads differently from an executive
briefing or a blog post, even if the underlying data is identical.

Rather than hard-coding tones or treating them as free-text strings, the
framework provides a **tone catalog** — a structured, extensible collection of
tone definitions that affect prompt generation across all text-producing agents
in a workflow.

### How Tone Works

1. The user selects a tone at **task input time** (or it defaults from the team
   config)
2. The framework resolves the tone ID to a **tone definition** containing a
   label, description, and prompt modifier
3. The prompt modifier is **injected into every text-producing agent's system
   prompt** as an additional instruction block
4. Agents that don't produce text (tool_user gathering data, action_executor
   deploying) are unaffected

### Built-in Tone Catalog

The framework ships with a default tone catalog. Users can extend it with
custom tones or override built-in ones.

| Tone ID          | Label          | Description                                                                      |
| ---------------- | -------------- | -------------------------------------------------------------------------------- |
| `objective`      | Objective      | Impartial and unbiased presentation of facts and findings                        |
| `formal`         | Formal         | Adheres to academic standards with sophisticated language and structure           |
| `analytical`     | Analytical     | Critical evaluation and detailed examination of data and theories                |
| `persuasive`     | Persuasive     | Convincing the audience of a particular viewpoint or argument                    |
| `informative`    | Informative    | Providing clear and comprehensive information on a topic                         |
| `explanatory`    | Explanatory    | Clarifying complex concepts and processes                                        |
| `descriptive`    | Descriptive    | Detailed depiction of phenomena, experiments, or case studies                    |
| `critical`       | Critical       | Judging the validity and relevance of the research and its conclusions           |
| `comparative`    | Comparative    | Juxtaposing different theories, data, or methods to highlight differences        |
| `speculative`    | Speculative    | Exploring hypotheses and potential implications or future research directions    |
| `reflective`     | Reflective     | Considering the process and personal insights or experiences                     |
| `narrative`      | Narrative      | Telling a story to illustrate findings or methodologies                          |
| `humorous`       | Humorous       | Light-hearted and engaging, making the content more relatable                    |
| `optimistic`     | Optimistic     | Highlighting positive findings and potential benefits                             |
| `pessimistic`    | Pessimistic    | Focusing on limitations, challenges, or negative outcomes                        |
| `concise`        | Concise        | Brief and to the point, minimal elaboration                                      |
| `executive`      | Executive      | High-level summary oriented toward decision-makers                               |

### Tone Definition Structure

Each tone entry contains:

```json
{
  "tone_id": "analytical",
  "label": "Analytical",
  "description": "Critical evaluation and detailed examination of data and theories",
  "prompt_modifier": "Adopt an analytical tone throughout your output. Critically evaluate the data and theories presented. Examine evidence in detail, identify patterns, draw comparisons, and highlight strengths and weaknesses in the underlying reasoning. Avoid unsupported assertions."
}
```

The `prompt_modifier` is the text that gets injected into agent prompts. It
should be 1–3 sentences of instruction that steer the LLM's writing style
without overriding the agent's primary task.

### Custom Tones

Users can define custom tones in their team config or task input:

```json
{
  "tone": {
    "tone_id": "investor_update",
    "label": "Investor Update",
    "description": "Professional, metrics-focused, forward-looking",
    "prompt_modifier": "Write in a professional tone suitable for investor communications. Lead with key metrics and outcomes. Be forward-looking and solution-oriented. Quantify impact wherever possible."
  }
}
```

### Tone is Optional

Tone is a **text-output concern**. Workflows that produce non-text outputs
(code artifacts, executed operations, action plans with no prose) will simply
ignore the tone setting. When no tone is specified, agents use their system
prompt as-is with no style injection.

### Configuration

Tone can be set at multiple levels (later overrides earlier):

```
System default → Team config → Task input
```

```json
{
  "team": "research_report",
  "instructions": "Impact of AI on healthcare",
  "tone": "formal",
  "language": "en"
}
```

```markdown
<!-- .task.md format -->
# Task: AI Healthcare Report

> **Team:** research_report
> **Tone:** formal
> **Language:** en

## Input

Impact of AI on healthcare...
```

---

## 3. Result Payload

The workflow produces a **result payload** — a structured object containing the
final content, metadata, actions taken, and references. The result payload is
the bridge between workflow execution and output export.

### Payload Structure

```
ResultPayload
├── title: str                # Workflow/task title
├── content: str              # Full assembled text
├── sections: list[Section]   # Ordered named content blocks
├── metadata: dict            # Arbitrary key-value pairs
├── references: list[Citation]# Source citations
├── actions: list[Action]     # Actions taken during workflow
├── cost_summary: CostReport  # Token usage, cost breakdown
└── step_results: list[Any]   # Raw per-step outputs
```

### Consuming Results Programmatically

Beyond file export, the result payload is available via:

- **API response** — `GET /api/workflows/{id}` returns the full payload as JSON
- **WebSocket stream** — the final message contains the payload
- **Callback hook** — register a function to receive the payload on completion
  (e.g., send to S3, email, webhook, Jira, Slack)

---

## 4. Output Pipeline Architecture (Decoupled Export)

How the result payload gets consumed is handled by **output publishers** — a
decoupled export layer that transforms the structured result into various
document formats.

### Design

```
Workflow → Result Payload → Publisher Registry → [PDF, DOCX, Markdown, HTML, JSON, ...]
```

### Publisher Plugin Interface

```
PublisherPlugin (protocol / base class)
├── publisher_id: str           # e.g. "pdf", "docx", "markdown", "html", "json"
├── description: str            # human-readable description
├── file_extension: str         # e.g. ".pdf", ".docx", ".md"
├── publish(payload, config) -> bytes | str   # render the result
└── manifest.yaml               # metadata, dependencies, config options
```

### Built-in Publishers

| Publisher    | Package                 | Dependencies                 | Output                    |
| ------------ | ----------------------- | ---------------------------- | ------------------------- |
| **Markdown** | `hiveflow-pub-markdown` | `aiofiles`                   | `.md` file                |
| **PDF**      | `hiveflow-pub-pdf`      | `pypandoc`, LaTeX engine     | `.pdf` with styled layout |
| **DOCX**     | `hiveflow-pub-docx`     | `pypandoc`                   | `.docx` with formatting   |
| **HTML**     | `hiveflow-pub-html`     | `pypandoc`, `jinja2`         | `.html` with template     |
| **JSON**     | `hiveflow-pub-json`     | —                            | `.json` structured data   |

### Layout Templates

Each publisher can accept a **layout template** that controls how the result
payload is assembled into a document. A default layout is provided:

1. Title + Date
2. Table of Contents (if applicable)
3. Executive Summary / Introduction
4. Section content (in order)
5. Actions Taken (for action-oriented workflows)
6. Conclusion / Next Steps
7. References / Sources
8. Appendix (cost breakdown, token usage)

Layout templates are overridable per team config and connect directly to the
`output_options` from the Output Type Routing configuration above (e.g.,
`include_introduction`, `include_table_of_contents` toggle layout sections).

### Publish Configuration

```json
{
  "publish": {
    "formats": ["pdf", "docx", "markdown"],
    "layout": "default",
    "style": "apa",
    "output_dir": "./output"
  }
}
```

---

> **Note:** HiveFlow is a framework library. User-facing frontends (Chainlit,
> React dashboards, etc.) belong in applications built on top of HiveFlow, not
> in the core package.

---

## 5. Source Mode

> **Note:** Source Mode is an **input** concern — it controls where data comes
> from, not what the output looks like. It is included here for historical
> continuity but logically pairs with the retrieval and data-processing
> infrastructure described in [05-data-processing.md](05-data-processing.md).

Workflows that involve data collection need to know **where to look**. The
framework provides a **source mode** abstraction that selects which retrieval
and ingestion pipelines are active for a given run. This is a task-level
setting, not a framework-level one — different runs of the same team
configuration can use different source modes.

### Built-in Source Modes

| Mode ID        | Label           | Pipeline                                                                        |
| -------------- | --------------- | ------------------------------------------------------------------------------- |
| `web`          | The Web         | Retriever plugins → Scraper plugins → Context pipeline                          |
| `local`        | Local Documents | Document loaders → Chunking → Embedding → Vector store                         |
| `hybrid`       | Hybrid          | Both web and local pipelines run in parallel; results merged and deduplicated   |
| `cloud`        | Cloud Storage   | Source plugins (S3, Azure Blob, SharePoint, etc.) → Document loaders → Pipeline |
| `mcp`          | MCP Sources     | MCP servers provide tools/data; agents decide what to fetch                      |
| `custom`       | Custom          | User specifies explicit source plugins and configuration                        |

### How Source Mode Works

1. The user selects a source mode at **task input time** (or it defaults to
   `web`)
2. The framework **activates the corresponding retrieval pipelines** and
   deactivates others
3. For `tool_user` agents, only the tools relevant to the active source mode
   are injected
4. For `hybrid` mode, both web and local pipelines run and results are merged
   before context compression

### Interaction with Existing Plugin Systems

Source mode is a **routing layer on top of** the existing plugin systems:

| Source Mode | Activates                                                          |
| ----------- | ------------------------------------------------------------------ |
| `web`       | Retriever plugins + Scraper plugins                                |
| `local`     | Document loaders + local vector store                              |
| `hybrid`    | All of the above                                                   |
| `cloud`     | Source plugins (see Cloud & Remote Document Sources) + doc loaders |
| `mcp`       | MCP client + connected MCP servers                                 |
| `custom`    | Explicitly listed plugins only                                     |

The source mode does **not** replace the plugin architecture — it selects which
subset of installed plugins participate in a given run.

### Configuration

```json
{
  "team": "research_report",
  "instructions": "Impact of AI on healthcare",
  "source_mode": "hybrid",
  "source_options": {
    "web": {
      "retrievers": ["tavily", "google"],
      "max_results_per_query": 10
    },
    "local": {
      "doc_path": "./docs/healthcare",
      "formats": ["pdf", "docx", "md"]
    }
  }
}
```

For `cloud` mode, source configuration points to the cloud source plugins:

```json
{
  "source_mode": "cloud",
  "source_options": {
    "provider": "azure_blob",
    "container": "research-docs",
    "path_prefix": "reports/2024/"
  }
}
```

### Source Mode is Optional

Workflows that don't involve data collection (e.g., code generation from a spec,
decision-making from provided data) can omit source mode entirely. When omitted,
no retrieval pipelines are activated unless agents explicitly call tools.

---

[Next: Context Management Strategy >](09-context-management.md)
