import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { FileCheckpointStorage, HiveFlow } from "@hiveflow/core";
import type { WorkflowDefinition } from "@hiveflow/core";

import {
  createLiveModelDefinition,
  createLiveRuntimeCatalog,
  resolveLiveExampleConfig,
  summarizeLiveExampleConfig
} from "../../shared/live.ts";

const checkpointDirectory = await mkdtemp(join(tmpdir(), "hiveflow-js-checkpoint-demo-"));
const live = resolveLiveExampleConfig();

try {
  const checkpointStorage = new FileCheckpointStorage(checkpointDirectory);
  const runtimeCatalog = createLiveRuntimeCatalog();
  const definition: WorkflowDefinition = {
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
    ],
    agents: [
      {
        id: "approver",
        role: "Human Approver",
        instructions: "Ask the operator for approval before continuing.",
        behavior: "human_gate",
        model: createLiveModelDefinition({
          id: "checkpoint-approver",
          baseURL: live.baseURL,
          modelId: live.modelId,
          apiMode: live.apiMode
        })
      },
      {
        id: "writer",
        role: "Writer",
        instructions: "Read the current JSON state and write the final operational announcement after approval.",
        behavior: "llm_only",
        model: createLiveModelDefinition({
          id: "checkpoint-writer",
          baseURL: live.baseURL,
          modelId: live.modelId,
          apiMode: live.apiMode
        })
      }
    ]
  };

  const initialHiveFlow = new HiveFlow({ checkpointStorage, runtimeCatalog });
  const pausedSession = await initialHiveFlow.runSessionFromDefinition({
    definition,
    initialState: {
      announcementRequest: "Approve and publish the release announcement."
    }
  });

  const resumedHiveFlow = new HiveFlow({ checkpointStorage, runtimeCatalog });
  const restoredSession = await resumedHiveFlow.loadSession({
    sessionId: pausedSession.sessionId
  });
  const restoredSessionSnapshot = {
    sessionId: restoredSession.sessionId,
    status: restoredSession.status,
    checkpointId: restoredSession.checkpointId,
    pendingRequests: restoredSession.pendingRequests
  };
  const resumedSession = await resumedHiveFlow.resumeSession({
    sessionId: pausedSession.sessionId,
    responses: { humanInput: "approved" }
  });

  console.log(
    JSON.stringify(
      {
        live: summarizeLiveExampleConfig(live),
        checkpointDirectory,
        pausedSession: {
          sessionId: pausedSession.sessionId,
          status: pausedSession.status,
          checkpointId: pausedSession.checkpointId,
          pendingRequests: pausedSession.pendingRequests
        },
        restoredSession: restoredSessionSnapshot,
        resumedSession: {
          sessionId: resumedSession.sessionId,
          status: resumedSession.status,
          result: resumedSession.result
        }
      },
      null,
      2
    )
  );
} finally {
  await rm(checkpointDirectory, { recursive: true, force: true });
}