import { Agent, HiveFlow, WorkflowEngine } from "@hiveflow/core";

import {
  createLiveModelAdapter,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig();

const researcher = new Agent({
  id: "researcher",
  role: "Researcher",
  instructions: "Produce concise research findings for the current task.",
  model: createLiveModelAdapter({ ...live, id: "subworkflow-researcher" }),
  behavior: "llm_only"
});

const reviewer = new Agent({
  id: "reviewer",
  role: "Reviewer",
  instructions: "Review the nested workflow findings.",
  model: createLiveModelAdapter({ ...live, id: "subworkflow-reviewer" }),
  behavior: "llm_only",
  prompt: (state) => `Review findings: ${String(state.researcherOutput ?? "")}`
});

const publisher = new Agent({
  id: "publisher",
  role: "Publisher",
  instructions: "Publish the parent workflow output.",
  model: createLiveModelAdapter({ ...live, id: "subworkflow-publisher" }),
  behavior: "llm_only",
  prompt: (state) =>
    `Findings: ${String(state.findings ?? "")}
Review: ${String(state.reviewDecision ?? "")}`
});

const nestedWorkflow = new WorkflowEngine({
  steps: [
    {
      id: "research",
      agent: "researcher",
      type: "sequential",
      next: "review"
    },
    {
      id: "review",
      agent: "reviewer",
      type: "sequential"
    }
  ]
});

const workflow = new WorkflowEngine({
  subWorkflows: {
    deep_research: {
      workflow: nestedWorkflow,
      agents: { researcher, reviewer }
    }
  },
  steps: [
    {
      id: "research-phase",
      agent: "research_team",
      type: "sub_workflow",
      team: "deep_research",
      inputMapping: { task: "researchQuestion" },
      outputMapping: {
        findings: "researcherOutput",
        reviewDecision: "reviewerOutput"
      },
      next: "publish"
    },
    {
      id: "publish",
      agent: "publisher",
      type: "sequential"
    }
  ]
});

const hiveflow = new HiveFlow();
const result = await hiveflow.run({
  workflow,
  agents: { publisher },
  initialState: {
    researchQuestion: "Explain why renewable energy improves resilience."
  }
});

console.log(
  JSON.stringify(
    {
      live: summarizeLiveExampleConfig(live),
      result
    },
    null,
    2
  )
);
