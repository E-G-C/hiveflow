import { ArchetypeLibrary, HiveFlow } from "@hiveflow/core";

import {
  createLiveModelDefinition,
  createLiveRuntimeCatalog,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig();
const archetypeLibrary = await ArchetypeLibrary.default();
const hiveflow = new HiveFlow({
  runtimeCatalog: createLiveRuntimeCatalog(),
  archetypeLibrary
});
const team = hiveflow.composeTeam({
  taskDescription: "Publish an executive release summary.",
  archetypes: ["writer"],
  model: createLiveModelDefinition({
    id: "team-generator-writer",
    baseURL: live.baseURL,
    modelId: live.modelId,
    apiMode: live.apiMode
  }),
  includeReview: false
});
const result = await hiveflow.runFromTeam({
  team,
  initialState: {
    task: "Publish an executive release summary."
  }
});

console.log(
  JSON.stringify(
    {
      live: summarizeLiveExampleConfig(live),
      availableArchetypes: hiveflow.archetypeLibrary().listArchetypes(),
      generatedTeam: team.toJSON(),
      result
    },
    null,
    2
  )
);