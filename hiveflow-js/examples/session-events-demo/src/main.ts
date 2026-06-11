import { Agent, WorkflowSession, WorkflowEngine } from "@hiveflow/core";

import {
  createLiveModelAdapter,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig();

const approver = new Agent({
  id: "approver",
  role: "Human Approver",
  instructions: "Ask the operator for approval before continuing.",
  model: createLiveModelAdapter({ ...live, id: "session-events-approver" }),
  behavior: "human_gate"
});

const writer = new Agent({
  id: "writer",
  role: "Writer",
  instructions: "Write the final operational announcement after approval.",
  model: createLiveModelAdapter({ ...live, id: "session-events-writer" }),
  behavior: "llm_only",
  prompt: (state) =>
    `Task: ${String(state.task ?? "")}\nApproval: ${String(state.humanInput ?? state.human_input ?? "")}`
});

const workflow = new WorkflowEngine({
  steps: [
    {
      id: "request-approval",
      agent: "approver",
      type: "human_gate",
      next: "publish"
    },
    {
      id: "publish",
      agent: "writer",
      type: "sequential"
    }
  ]
});

const session = new WorkflowSession({
  workflow,
  agents: { approver, writer },
  initialState: {
    task: "Approve and publish the release announcement."
  }
});

const eventsPromise = collectEvents(session.events());

await session.run();

const pendingAfterRun = session.pendingRequests;

await session.resume({
  humanInput: "approved"
});

const events = await eventsPromise;

console.log(
  JSON.stringify(
    {
      sessionId: session.sessionId,
      status: session.status,
      pendingAfterRun,
      live: summarizeLiveExampleConfig(live),
      events,
      result: session.result
    },
    null,
    2
  )
);

async function collectEvents(events: AsyncIterable<unknown>): Promise<unknown[]> {
  const collected = [] as unknown[];

  for await (const event of events) {
    collected.push(event);
  }

  return collected;
}