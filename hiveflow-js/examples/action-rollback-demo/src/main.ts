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
    "Use exactly one tool call: deploy_release with environment 'staging' and version '2026.03.06'. If it fails, rely on rollback_deploy to recover the deployment.",
  model: createLiveModelAdapter({ ...live, id: "action-rollback-deployer" }),
  behavior: "action_executor",
  actionPolicy: "auto",
  rollbackOnFailure: true,
  rollbackAction: "rollback_deploy",
  tools: {
    deploy_release: {
      description: "Deploy a release to the requested environment.",
      execute: async (input) => {
        const typedInput = input as { environment: string; version: string };
        executedActions.push(`deploy:${typedInput.environment}:${typedInput.version}`);
        throw new Error("Deployment verification failed after rollout started.");
      }
    },
    rollback_deploy: {
      description: "Rollback the deployment if a downstream action fails.",
      execute: async () => {
        executedActions.push("rollback:deploy_release");
        return {
          ok: true,
          restoredDeploymentId: "dep-demo"
        };
      }
    }
  }
});

const workflow = new WorkflowEngine({
  steps: [
    {
      id: "deploy",
      agent: "deployer",
      type: "sequential"
    }
  ]
});

const hiveflow = new HiveFlow();
const primaryTask =
  "Use deploy_release for staging version 2026.03.06.";
const fallbackTask =
  "Do not answer with prose. You must call deploy_release with environment 'staging' and version '2026.03.06'. If it fails, rely on rollback_deploy.";

const result = await runUntilRollback([primaryTask, fallbackTask, fallbackTask]);

console.log(
  JSON.stringify(
    {
      live: summarizeLiveExampleConfig(live),
      result,
      executedActions,
      ...(!executedActions.includes("rollback:deploy_release")
        ? {
            note:
              "The live model did not emit the failing deploy_release tool call after multiple attempts, so this run completed without exercising rollback_on_failure."
          }
        : {})
    },
    null,
    2
  )
);

async function runWorkflowWithTask(task: string) {
  executedActions.length = 0;

  return hiveflow.run({
    workflow,
    agents: { deployer },
    initialState: { task }
  });
}

async function runUntilRollback(tasks: string[]) {
  let result = await runWorkflowWithTask(tasks[0] ?? fallbackTask);

  for (const task of tasks.slice(1)) {
    if (executedActions.includes("rollback:deploy_release")) {
      return result;
    }

    result = await runWorkflowWithTask(task);
  }

  return result;
}