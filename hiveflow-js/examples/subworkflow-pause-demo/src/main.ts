import { Agent, HiveFlow, WorkflowEngine } from "@hiveflow/core";

import {
  createLiveModelAdapter,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig();

const reviewer = new Agent({
  id: "reviewer",
  role: "Reviewer",
  instructions: "Pause for approval before publication.",
  model: createLiveModelAdapter({ ...live, id: "subworkflow-pause-reviewer" }),
  behavior: "human_gate"
});

const publisher = new Agent({
  id: "publisher",
  role: "Publisher",
  instructions: "Publish the approved launch brief.",
  model: createLiveModelAdapter({ ...live, id: "subworkflow-pause-publisher" }),
  behavior: "llm_only",
  prompt: (state) => `Approval: ${String(state.reviewDecision ?? "pending")}`
});

const nestedWorkflow = new WorkflowEngine({
  steps: [
    {
      id: "review",
      agent: "reviewer",
      type: "human_gate"
    }
  ]
});

const workflow = new WorkflowEngine({
  subWorkflows: {
    review_team: {
      workflow: nestedWorkflow,
      agents: { reviewer }
    }
  },
  steps: [
    {
      id: "review-phase",
      agent: "review_team",
      type: "sub_workflow",
      team: "review_team",
      outputMapping: {
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
const paused = await hiveflow.run({
  workflow,
  agents: { publisher },
  initialState: {
    task: "Approve the launch brief for publication."
  }
});

if (paused.status !== "paused") {
  throw new Error(`Expected paused result from nested sub_workflow demo, received '${paused.status}'.`);
}

const resumed = await hiveflow.resume({
  workflow,
  agents: { publisher },
  pausedResult: paused,
  responses: {
    humanInput: "Approved for publication."
  }
});

console.log(
  JSON.stringify(
    {
      pausedRequest: paused.pendingHumanInput,
      pauseContext: paused.pauseContext,
      live: summarizeLiveExampleConfig(live),
      resumed
    },
    null,
    2
  )
);