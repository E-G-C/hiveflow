import { ArchetypeLibrary, TeamConfiguration } from "@hiveflow/core";
import type { WorkflowEvent } from "@hiveflow/core";

import {
  DEFAULT_LIVE_TOOL_MODEL_ID,
  createLiveModelDefinition,
  createLiveRuntimeCatalog,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig({
  modelId: process.env.HIVEFLOW_LIVE_OPENAI_MODEL ?? DEFAULT_LIVE_TOOL_MODEL_ID
});
const archetypeLibrary = ArchetypeLibrary.fromBuiltIns();

const team = new TeamConfiguration({
  teamName: "dynamic_collaboration_demo",
  collaboration: {
    enabled: true,
    maxDelegationDepth: 3,
    maxSpawnedAgents: 3,
    delegationTimeoutSeconds: 30,
    budgetPolicy: "inherit_parent"
  },
  agents: [
    {
      id: "spawner",
      role: "Spawner",
      instructions:
        "Call spawn_agent exactly once with archetype 'writer'. Do not answer with prose.",
      behavior: "orchestrator",
      model: createLiveModelDefinition({
        id: "dynamic-collaboration-spawner",
        baseURL: live.baseURL,
        modelId: live.modelId,
        apiMode: live.apiMode
      })
    },
    {
      id: "delegator",
      role: "Delegator",
      instructions:
        "Assume a spawned writer named 'spawned_writer_1' is available. Call delegate_task exactly once to that agent with the task 'Write one concise sentence explaining why renewable energy matters.' After the delegated result returns, answer with 'Delegated collaboration completed successfully.' followed by the delegated sentence.",
      behavior: "orchestrator",
      model: createLiveModelDefinition({
        id: "dynamic-collaboration-delegator",
        baseURL: live.baseURL,
        modelId: live.modelId,
        apiMode: live.apiMode
      })
    }
  ],
  workflow: {
    steps: [
      {
        id: "spawn",
        agent: "spawner",
        type: "sequential",
        next: "delegate"
      },
      {
        id: "delegate",
        agent: "delegator",
        type: "sequential"
      }
    ]
  }
});

const runtime = createLiveRuntimeCatalog({ archetypeLibrary }).build(team.toWorkflowDefinition());
const events: WorkflowEvent[] = [];

runtime.workflow.onEvent((event) => {
  events.push(event);
});

const result = await runtime.workflow.execute({
  agents: runtime.agents,
  initialState: {
    collaborationDemo: "Spawn a writer and delegate one concise renewable-energy explanation."
  }
});

console.log(
  JSON.stringify(
    {
      live: summarizeLiveExampleConfig(live),
      team: team.toJSON(),
      events,
      result,
      ...(result.status === "completed"
        ? {}
        : {
            note:
              "The live collaboration runtime surfaced a tool-loop failure on this run. The event log above shows how far the endpoint progressed before stopping."
          })
    },
    null,
    2
  )
);