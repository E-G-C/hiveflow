import { HiveFlow } from "@hiveflow/core";

import {
  createLiveModelAdapter,
  createLiveModelDefinition,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const taskDescription =
  "Create a concise research-brief team about battery storage trends with a researcher that needs web_search, a writer, and a reviewer.";
const live = resolveLiveExampleConfig();

const hiveflow = new HiveFlow();

try {
  const result = await hiveflow.composeTeamFromLLM({
    taskDescription,
    llm: createLiveModelAdapter({ ...live, id: "llm-team-generator" }),
    model: createLiveModelDefinition({
      id: "llm-team-generator-default",
      baseURL: live.baseURL,
      modelId: live.modelId,
      apiMode: live.apiMode
    }),
    availableTools: ["web_search"]
  });

  console.log(
    JSON.stringify(
      {
        live: summarizeLiveExampleConfig(live),
        taskDescription,
        hasBlockingGaps: result.hasBlockingGaps,
        capabilityGaps: result.capabilityGaps,
        newArchetypes: result.newArchetypes,
        generatedTeam: result.config.toJSON()
      },
      null,
      2
    )
  );
} catch (error) {
  console.log(
    JSON.stringify(
      {
        live: summarizeLiveExampleConfig(live),
        taskDescription,
        generatedTeam: null,
        note:
          "The live model did not return a valid TeamConfiguration after validation retries.",
        error: error instanceof Error ? error.message : String(error)
      },
      null,
      2
    )
  );
}