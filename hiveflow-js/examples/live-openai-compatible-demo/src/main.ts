import { Agent, HiveFlow, WorkflowEngine } from "@hiveflow/core";

import {
  createLiveModelAdapter,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

async function main(): Promise<void> {
  const live = resolveLiveExampleConfig();

  const analyst = new Agent({
    id: "analyst",
    role: "Analyst",
    instructions: "Produce concise factual notes for the current task.",
    model: createLiveModelAdapter({ ...live, id: "live-openai-analyst" }),
    behavior: "llm_only"
  });

  const writer = new Agent({
    id: "writer",
    role: "Writer",
    instructions: "Write a concise synthesis from the prior state.",
    model: createLiveModelAdapter({ ...live, id: "live-openai-writer" }),
    behavior: "llm_only",
    prompt: (state) =>
      `Task: ${String(state.task ?? "")}\nNotes: ${String(state.analystOutput ?? "")}`
  });

  const workflow = new WorkflowEngine({
    steps: [
      {
        id: "analyze",
        agent: "analyst",
        type: "sequential",
        next: "write"
      },
      {
        id: "write",
        agent: "writer",
        type: "sequential"
      }
    ]
  });

  const hiveflow = new HiveFlow();
  let result;
  try {
    result = await hiveflow.run({
      workflow,
      agents: { analyst, writer },
      initialState: {
        task: "Explain in two short paragraphs why renewable energy matters."
      }
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const cause =
      error instanceof Error && error.cause instanceof Error
        ? ` Cause: ${error.cause.message}`
        : "";
    throw new Error(
      `Live validation failed against ${live.baseURL} using model ${live.modelId} in ${live.apiMode} mode: ${message}${cause}`
    );
  }

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
}

await main();