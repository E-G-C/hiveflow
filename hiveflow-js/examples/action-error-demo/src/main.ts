import { Agent, HiveFlow, WorkflowEngine } from "@hiveflow/core";

import {
  DEFAULT_LIVE_TOOL_MODEL_ID,
  createLiveModelAdapter,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const executedActions: string[] = [];
const live = resolveLiveExampleConfig({
  modelId: process.env.HIVEFLOW_LIVE_OPENAI_MODEL ?? DEFAULT_LIVE_TOOL_MODEL_ID
});

const deployer = new Agent({
  id: "deployer",
  role: "Deployer",
  instructions:
    "Use exactly one tool call: deploy_release with environment 'staging' and version '2026.03.06'.",
  model: createLiveModelAdapter({ ...live, id: "action-error-deployer" }),
  behavior: "action_executor",
  actionPolicy: "confirm_on_error",
  tools: {
    deploy_release: {
      description: "Deploy a release to the requested environment.",
      execute: async (input) => {
        const typedInput = input as { environment: string; version: string };
        executedActions.push(`deploy:${typedInput.environment}:${typedInput.version}`);
        throw new Error("Deployment verification failed after rollout started.");
      }
    }
  }
});

const announcer = new Agent({
  id: "announcer",
  role: "Announcer",
  instructions: "Summarize the acknowledged deployment state.",
  model: createLiveModelAdapter({ ...live, id: "action-error-announcer" }),
  behavior: "llm_only",
  prompt: (state) =>
    `Summarize the acknowledged deployment using these action records:\n${JSON.stringify(
      state.deployerActionRecords ?? [],
      null,
      2
    )}\nAcknowledged: ${String(state.deployerActionErrorAcknowledged ?? "")}`
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
  "Use deploy_release for staging version 2026.03.06.";
const fallbackTask =
  "Do not answer with prose. You must call deploy_release with environment 'staging' and version '2026.03.06'.";

const session = await runUntilPaused([primaryTask, fallbackTask, fallbackTask]);

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
  await session.resume({ deployerActionErrorAcknowledged: true });
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
              "The live model did not emit the failing deploy_release tool call after multiple attempts, so this run completed without exercising confirm_on_error."
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