# HiveFlow — Universal Multi-Agent Problem-Solving Framework (v2)

> **Version:** 2.0
> **Date:** 2026-02-12
> **Previous version:** [hiveflow-requirements.md](hiveflow-requirements.md) (v1, research-centric)
> **Status:** Draft
> **Changelog:** Generalized from research-report generation to a universal
> problem-solving framework. Added action-orientation, cross-domain examples,
> Mermaid workflow diagrams, and an expanded agent execution model.

---

## Objective

Create a **reusable, generic multi-agent framework** that enables any multi-step
collaborative workflow to be assembled from a universal agent definition
specialized at creation time. Agents collaborate to **produce an output, take
actions, or decide what actions to take** in service of solving a given problem.

The output of a HiveFlow workflow is not limited to documents. It can be:

- A **document** (report, plan, contract, specification)
- A **decision** (recommended course of action with supporting evidence)
- A set of **executed operations** (API calls, file modifications, deployments)
- A **plan** (structured steps for humans or machines to follow)
- An **artifact** (code, configuration files, test suites)
- Any **combination** of the above

This version generalizes the framework from the research-report domain explored
in v1 into a universal problem-solving engine.

---

## Background & Observations

In the original `gpt-researcher` codebase, specialized agents collaborate to
produce a research report: Chief Editor, Editor, Researcher, Reviewer, Reviser,
Writer, Publisher, and an optional Human agent. Analysis reveals that **most
agents follow the same fundamental pattern** — they receive a system prompt,
call the LLM, and return text. The only things that distinguish them are:

- Their **system prompt** (identity and instructions)
- Their **position in the workflow** (what comes before and after them)
- Their **tools/capabilities** (most have none; only the Researcher wraps an
  external search/scrape engine)

This insight leads to a more powerful generalization: the research pipeline's
stages — planning, information gathering, drafting, reviewing, revising,
publishing — **map to any multi-step problem**:

| Research Pipeline | Universal Pipeline        | General Purpose                                |
| ------------------- | ----------------------------- | ---------------------------------------------- |
| Editor plans        | **Decomposition**             | Break the problem into sub-tasks               |
| Researcher gathers  | **Data Collection**           | Use tools to collect needed data               |
| Writer drafts       | **Production / Execution**    | Generate candidate outputs or perform actions  |
| Reviewer evaluates  | **Evaluation**                | Assess quality, correctness, success criteria  |
| Reviser iterates    | **Iteration**                 | Refine based on evaluation feedback            |
| Publisher emits     | **Emission**                  | Finalize and emit the result                   |

The current architecture can therefore be collapsed into a single parameterized
agent class that receives its specialization as configuration rather than code,
and extended to support **action-taking** (not just text generation) as a
first-class output.

---

## Document Structure

This requirements document has been split into the following sections for easier navigation:

| # | File | Topics |
|---|------|--------|
| 1 | [01-core-architecture.md](01-core-architecture.md) | Universal Agent Class, Dynamic Team Composition, TeamGenerator & Archetype Library, Workflow Graph Definition |
| 2 | [02-workflows.md](02-workflows.md) | The Generalized Workflow (6 stages), Cross-Domain Applications (Software Engineering, Decision-Making, Incident Response, Content Creation) |
| 3 | [03-agents-and-teams.md](03-agents-and-teams.md) | Team Configuration Schema, Agent Behavior Types, Action-Oriented Agents |
| 4 | [04-plugins.md](04-plugins.md) | Tool Plugin Architecture, LLM Provider Plugin Architecture |
| 5 | [05-data-processing.md](05-data-processing.md) | State Management, Data Processing Infrastructure (Retrievers, Scrapers, Context Compression, Embeddings, Vector Stores, Document Loading, Citations) , Source Curation & Credibility Ranking |
| 6 | [06-integrations.md](06-integrations.md) | Dynamic Agent / Role Selection, MCP Integration, Conversational Memory |
| 7 | [07-entry-points.md](07-entry-points.md) | Entry Points (CLI, Package, API, Docker), Cloud & Remote Document Sources |
| 8 | [08-output-pipeline.md](08-output-pipeline.md) | Output Type Routing, Tone & Style System, Result Payload, Publisher Pipeline, Source Mode |
| 9 | [09-context-management.md](09-context-management.md) | Context Management Strategy (Divide-and-Conquer, Summary Propagation, SummaryGenerator, Code-Level Assembly) |
| 10 | [10-configuration-and-operations.md](10-configuration-and-operations.md) | Configuration System, Resilience & Error Handling, Prompt Template Library, Streaming & Message Protocol, Recursive Exploration |
| ~~11~~ | *(merged into 08)* | *(Output Pipeline Architecture — now in 08-output-pipeline.md)* |
| 12 | [12-document-input.md](12-document-input.md) | Document Input Pipeline (3-phase design) |
| 13 | [13-dynamic-agent-collaboration.md](13-dynamic-agent-collaboration.md) | Dynamic Agent Collaboration (Delegation, Spawning, Messaging, Task Planning) |
| 14 | [14-task-preprocessing.md](14-task-preprocessing.md) | Task Preprocessing and Large-Input Context Management |
| 15 | [15-typescript-parity-matrix.md](15-typescript-parity-matrix.md) | Python/TypeScript parity matrix, feature backlog, example-family tracking |
| 99 | [99-appendix.md](99-appendix.md) | Coverage Summary |

The complete, unsplit document is preserved as [hiveflow-requirements-v2.md](hiveflow-requirements-v2.md).
