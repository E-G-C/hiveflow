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
  instructions:
    "Inspect the assigned system area and return exactly one concise sentence describing the highest-priority reliability concern.",
  model: createLiveModelAdapter({ ...live, id: "branching-researcher" }),
  behavior: "llm_only",
  prompt: (state) =>
    `Inspect the ${String(state.currentItem ?? state.current_item ?? "")} system area and return exactly one sentence.`
});

const reviewer = new Agent({
  id: "reviewer",
  role: "Reviewer",
  instructions:
    "Act as a strict release-review gate. Raw findings must be rejected with 'Needs revision.' A numbered three-item plan should be approved with 'Approved.'",
  model: createLiveModelAdapter({ ...live, id: "branching-reviewer" }),
  behavior: "llm_only",
  prompt: (state) => {
    const revisedPlan = String(state.reviserOutput ?? "").trim();
    if (revisedPlan) {
      return `Review this numbered action plan. If it contains exactly three numbered priorities, respond with 'Approved.' followed by one sentence.\n${revisedPlan}`;
    }

    return `Review these raw findings. You must respond with 'Needs revision.' followed by one sentence requesting a numbered priority plan.\n${String(
      state.researcherOutput ?? ""
    )}`;
  }
});

const reviser = new Agent({
  id: "reviser",
  role: "Reviser",
  instructions:
    "Rewrite the findings into exactly three numbered operational priorities. End with the sentence 'Ready for approval.'",
  model: createLiveModelAdapter({ ...live, id: "branching-reviser" }),
  behavior: "llm_only",
  prompt: (state) =>
    `Research findings:\n${String(state.researcherOutput ?? "")}\n\nReviewer feedback:\n${String(state.reviewerOutput ?? "")}`
});

const publisher = new Agent({
  id: "publisher",
  role: "Publisher",
  instructions:
    "Turn the approved plan into a concise executive summary with one sentence per priority.",
  model: createLiveModelAdapter({ ...live, id: "branching-publisher" }),
  behavior: "llm_only",
  prompt: (state) => `Publish this approved plan:\n${String(state.reviserOutput ?? state.researcherOutput ?? "")}`
});

const workflow = new WorkflowEngine({
  steps: [
    {
      id: "research",
      agent: "researcher",
      type: "parallel_fan_out",
      next: "review"
    },
    {
      id: "review",
      agent: "reviewer",
      type: "conditional",
      nextOnReject: "revise",
      nextOnAccept: "publish",
      maxIterations: 3
    },
    {
      id: "revise",
      agent: "reviser",
      type: "sequential",
      next: "review"
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
  agents: { researcher, reviewer, reviser, publisher },
  initialState: {
    task: "Prioritize reliability work across the platform.",
    parallelItems: ["auth", "billing", "notifications"]
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