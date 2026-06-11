import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { HiveFlow, TeamConfiguration, TeamLibrary } from "@hiveflow/core";

import {
  createLiveModelDefinition,
  createLiveRuntimeCatalog,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig();

const directory = await mkdtemp(join(tmpdir(), "hiveflow-js-team-config-demo-"));

try {
  const team = new TeamConfiguration({
    teamName: "release_notes",
    version: "1.0.0",
    description: "Generate a release note from a persisted team configuration.",
    agents: [
      {
        id: "researcher",
        role: "Researcher",
        instructions: "Read the current JSON state and collect the three most important release highlights.",
        behavior: "llm_only",
        model: createLiveModelDefinition({
          id: "team-config-researcher",
          baseURL: live.baseURL,
          modelId: live.modelId,
          apiMode: live.apiMode
        })
      },
      {
        id: "writer",
        role: "Writer",
        instructions: "Read the current JSON state and write the final release note.",
        behavior: "llm_only",
        model: createLiveModelDefinition({
          id: "team-config-writer",
          baseURL: live.baseURL,
          modelId: live.modelId,
          apiMode: live.apiMode
        })
      }
    ],
    workflow: {
      steps: [
        {
          agent: "researcher",
          type: "sequential",
          next: "writer"
        },
        {
          agent: "writer",
          type: "sequential"
        }
      ]
    }
  });
  const teamPath = join(directory, "release_notes.json");

  await team.saveJson(teamPath);

  const teamLibrary = await TeamLibrary.fromDirectory(directory);
  const hiveflow = new HiveFlow({
    runtimeCatalog: createLiveRuntimeCatalog(),
    teamLibrary
  });
  const result = await hiveflow.runFromTeam({
    team: "release_notes",
    initialState: {
      releaseRequest: "Summarize the deployment release."
    }
  });

  console.log(
    JSON.stringify(
      {
        live: summarizeLiveExampleConfig(live),
        availableTeams: teamLibrary.listTeams(),
        result
      },
      null,
      2
    )
  );
} finally {
  await rm(directory, { recursive: true, force: true });
}