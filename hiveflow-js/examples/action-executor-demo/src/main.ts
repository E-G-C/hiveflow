import { Agent, HiveFlow, WorkflowEngine } from "@hiveflow/core";

import {
  DEFAULT_LIVE_TOOL_MODEL_ID,
  createLiveModelAdapter,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const executedActions: Array<{ environment: string; version: string }> = [];
const live = resolveLiveExampleConfig({
  modelId: process.env.HIVEFLOW_LIVE_OPENAI_MODEL ?? DEFAULT_LIVE_TOOL_MODEL_ID
});

const deployer = new Agent({
  id: "deployer",
  role: "Deployer",
  instructions:
    "Use exactly one tool call: deploy_release with environment 'staging' and version '2026.03.06'. Do not call any other tools or answer without the tool call.",
  model: createLiveModelAdapter({ ...live, id: "action-executor-deployer" }),
  behavior: "action_executor",
  actionPolicy: "require_approval",
  tools: {
    deploy_release: {
      description: "Deploy a release to the requested environment.",
      execute: async (input) => {
        const typedInput = input as { environment: string; version: string };
        executedActions.push(typedInput);
        return {
          ok: true,
          deploymentId: "dep-demo",
          environment: typedInput.environment,
          version: typedInput.version
        };
      }
    }
  }
});

const announcer = new Agent({
  id: "announcer",
  role: "Announcer",
  instructions: "Summarize the approved deployment outcome.",
  model: createLiveModelAdapter({ ...live, id: "action-executor-announcer" }),
  behavior: "llm_only",
  prompt: (state) =>
    `Summarize the approved deployment using these action records:\n${JSON.stringify(
      state.deployerActionRecords ?? [],
      null,
      2
    )}`
});

const workflow = new WorkflowEngine({
  steps: [
    {
      id: "deploy",
      agent: "deployer",
      type: "sequential",
      next: "announce"
    },
    {
      id: "announce",
      agent: "announcer",
      type: "sequential"
    }
  ]
});

const hiveflow = new HiveFlow();
const primaryTask =
  "Use the deploy_release tool to deploy version 2026.03.06 to staging, then wait for approval before execution.";
const fallbackTask =
  "Do not answer with prose. You must call deploy_release with environment 'staging' and version '2026.03.06', then stop and wait for approval.";

const session = await runUntilPaused([primaryTask, fallbackTask, fallbackTask, fallbackTask]);

const pausedSession =
  session.status === "paused"
    ? {
        sessionId: session.sessionId,
        status: session.status,
        pendingRequests: session.pendingRequests,
        result: session.result
      }
    : null;

if (session.status === "paused") {
  await session.resume({ deployerActionApproved: true });
}

console.log(
  JSON.stringify(
    {
      pausedSession,
      resumedSession: {
        sessionId: session.sessionId,
        status: session.status,
        result: session.result
      },
      live: summarizeLiveExampleConfig(live),
      executedActions,
      ...(session.status === "paused"
        ? {}
        : {
            note:
              "The live model did not emit a deploy_release tool call after multiple attempts, so this run completed without exercising the approval pause."
          })
    },
    null,
    2
  )
);

async function runSessionWithTask(task: string) {
  const session = hiveflow.createSession({
    workflow,
    agents: { deployer, announcer },
    initialState: { task }
  });

  await session.run();
  return session;
}

async function runUntilPaused(tasks: string[]) {
  let session = await runSessionWithTask(tasks[0] ?? fallbackTask);

  for (const task of tasks.slice(1)) {
    if (session.status === "paused") {
      return session;
    }

    session = await runSessionWithTask(task);
  }

  return session;
}
