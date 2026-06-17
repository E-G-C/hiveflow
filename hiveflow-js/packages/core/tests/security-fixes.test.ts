import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  Agent,
  CheckpointError,
  CollaborationRuntime,
  FileCheckpointStorage,
  WorkflowEngine,
  WorkflowSession,
  createMockModel,
  createWorkflowCheckpoint
} from "../src/index.js";
import type { ToolExecutionContext, WorkflowData, WorkflowResult } from "../src/index.js";
import {
  normalizeActionRecord,
  normalizeRollbackRecord,
  safeClone,
  safeSerialize
} from "../src/internal.js";

function createPausedCheckpoint(sessionId: string, checkpointId: string, createdAt: number) {
  const pausedResult: WorkflowResult = {
    status: "paused",
    state: { task: "demo" },
    stepResults: []
  };

  return createWorkflowCheckpoint({ sessionId, checkpointId, pausedResult, createdAt });
}

function createToolContext(): ToolExecutionContext {
  return { state: {}, messages: [], stepId: "step-1" };
}

describe("FileCheckpointStorage path-traversal hardening (H1)", () => {
  it("rejects traversal/empty session ids without touching the storage root", async () => {
    const root = await mkdtemp(join(tmpdir(), "hiveflow-h1-"));
    try {
      const storage = new FileCheckpointStorage(join(root, "checkpoints"));
      await storage.save(createPausedCheckpoint("safe-session", "cp-1", 1000));

      for (const unsafe of ["..", ".", ""]) {
        await expect(storage.delete(unsafe)).rejects.toThrow(CheckpointError);
      }

      // The seeded session must survive the rejected deletions.
      const sessions = await storage.listSessions();
      expect(sessions).toContain("safe-session");
      const loaded = await storage.load("safe-session");
      expect(loaded?.checkpointId).toBe("cp-1");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects traversal checkpoint ids", async () => {
    const root = await mkdtemp(join(tmpdir(), "hiveflow-h1-"));
    try {
      const storage = new FileCheckpointStorage(join(root, "checkpoints"));
      await expect(storage.load("safe-session", "..")).rejects.toThrow(CheckpointError);
      await expect(storage.load("safe-session", ".")).rejects.toThrow(CheckpointError);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("Delegated state prototype-pollution guard (H2)", () => {
  it("skips __proto__/constructor/prototype keys from LLM-supplied context", async () => {
    const model = createMockModel("mock-h2", () => ({ text: "done" }));
    const orchestrator = new Agent({
      id: "orchestrator",
      role: "Orchestrator",
      instructions: "Coordinate work.",
      model,
      behavior: "orchestrator"
    });

    const captured: WorkflowData[] = [];
    const target = new Agent({
      id: "target",
      role: "Target",
      instructions: "Complete delegated work.",
      model,
      behavior: "llm_only"
    });
    const originalExecute = target.execute.bind(target);
    target.execute = async (state: WorkflowData, executionContext = {}) => {
      captured.push(state);
      return originalExecute(state, executionContext);
    };

    const runtime = new CollaborationRuntime({ config: { enabled: true } });
    runtime.registerInitialAgents({ target });
    const tools = runtime.createOrchestratorTools(orchestrator);

    // JSON.parse yields an own enumerable "__proto__" key (the classic vector).
    const malicious = JSON.parse(
      '{"__proto__": {"polluted": true}, "constructor": {"hacked": 1}, "prototype": {"hacked": 2}, "safe": "value"}'
    ) as WorkflowData;

    await tools.delegate_task?.execute(
      { task: "Process payload.", delegate_to: "target", context: malicious },
      createToolContext()
    );

    const received = captured[0];
    expect(received).toBeDefined();
    expect(Object.prototype.hasOwnProperty.call(received, "__proto__")).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(received, "constructor")).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(received, "prototype")).toBe(false);
    expect(received?.safe).toBe("value");
    expect((received as Record<string, unknown>).polluted).toBeUndefined();
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });
});

describe("Session event delivery on close (M1)", () => {
  it("delivers events queued before close to a slow consumer", async () => {
    const model = createMockModel("mock-m1", () => ({ text: "done" }));
    const worker = new Agent({
      id: "worker",
      role: "Worker",
      instructions: "Perform the task.",
      model,
      behavior: "llm_only"
    });
    const workflow = new WorkflowEngine({
      steps: [{ id: "do", agent: "worker", type: "sequential" }]
    });
    const session = new WorkflowSession({
      workflow,
      agents: { worker },
      initialState: { task: "demo" }
    });

    // Subscribe but do not drain until after the workflow completes and the
    // event channel has been closed.
    const consumer = session.events();
    await session.run();
    expect(session.status).toBe("completed");

    const events: string[] = [];
    for await (const event of consumer) {
      events.push(event.type);
    }

    expect(events).toContain("step_start");
    expect(events).toContain("step_complete");
  });
});

describe("Safe serialization helpers (M4)", () => {
  it("clones objects with circular references without throwing", () => {
    const node: Record<string, unknown> = { name: "root" };
    node.self = node;

    const clone = safeClone(node) as Record<string, unknown>;
    expect(clone.name).toBe("root");
    expect(clone.self).toBeUndefined();
  });

  it("preserves shared (non-circular) sibling references", () => {
    const shared = { value: 1 };
    const clone = safeClone({ a: shared, b: shared }) as {
      a?: { value: number };
      b?: { value: number };
    };

    expect(clone.a?.value).toBe(1);
    expect(clone.b?.value).toBe(1);
  });

  it("converts BigInt to string and drops functions", () => {
    const serialized = safeSerialize({ big: 10n, fn: () => 1, keep: "ok" });
    const parsed = JSON.parse(serialized) as Record<string, unknown>;

    expect(parsed.big).toBe("10");
    expect(parsed.fn).toBeUndefined();
    expect(parsed.keep).toBe("ok");
  });

  it("returns the original reference when serialization fails (not null)", () => {
    const value = {
      get boom(): never {
        throw new Error("toJSON failure");
      }
    };

    expect(safeClone(value)).toBe(value);
  });
});

describe("Action/rollback normalizer validation (L1)", () => {
  it("normalizes an invalid action record status/policy to safe defaults", () => {
    const normalized = normalizeActionRecord({
      actionId: "a1",
      agentId: "agent-1",
      tool: "search",
      status: "totally-bogus",
      policy: "totally-bogus",
      toolCallId: "call-1"
    });

    expect(normalized).toBeDefined();
    expect(normalized?.status).toBe("error");
    expect(normalized?.policy).toBe("require_approval");
  });

  it("preserves valid action record status/policy", () => {
    const normalized = normalizeActionRecord({
      actionId: "a1",
      agentId: "agent-1",
      tool: "search",
      status: "completed",
      policy: "auto",
      toolCallId: "call-1"
    });

    expect(normalized?.status).toBe("completed");
    expect(normalized?.policy).toBe("auto");
  });

  it("normalizes an invalid rollback record status to a safe default", () => {
    const normalized = normalizeRollbackRecord({
      rollbackId: "r1",
      agentId: "agent-1",
      rollbackAction: "undo",
      status: "bogus"
    });

    expect(normalized?.status).toBe("error");
  });
});

describe("Checkpoint listing tolerates corrupt files (L3)", () => {
  it("skips an unreadable checkpoint file and still loads the rest", async () => {
    const root = await mkdtemp(join(tmpdir(), "hiveflow-l3-"));
    try {
      const storage = new FileCheckpointStorage(join(root, "checkpoints"));
      await storage.save(createPausedCheckpoint("session-a", "cp-1", 1000));
      await storage.save(createPausedCheckpoint("session-a", "cp-2", 2000));

      // Corrupt the older checkpoint file on disk.
      await writeFile(
        join(root, "checkpoints", "session-a", "cp-1.json"),
        "{ not valid json",
        "utf8"
      );

      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      try {
        const checkpoints = await storage.listCheckpoints("session-a");
        expect(checkpoints).toHaveLength(1);
        expect(checkpoints[0]?.checkpointId).toBe("cp-2");
        expect(warnSpy).toHaveBeenCalledTimes(1);

        const latest = await storage.load("session-a");
        expect(latest?.checkpointId).toBe("cp-2");
      } finally {
        warnSpy.mockRestore();
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("Spawn cap on the default-delegate path (L5)", () => {
  it("rejects an auto-delegation that would exceed the spawn cap", async () => {
    const model = createMockModel("mock-l5", () => ({ text: "done" }));
    const orchestrator = new Agent({
      id: "orchestrator",
      role: "Orchestrator",
      instructions: "Coordinate work.",
      model,
      behavior: "orchestrator"
    });

    const runtime = new CollaborationRuntime({
      config: { enabled: true, maxSpawnedAgents: 1 }
    });
    const tools = runtime.createOrchestratorTools(orchestrator);

    // First auto-delegation spawns the single permitted default delegate.
    await tools.delegate_task?.execute({ task: "Summarize the findings." }, createToolContext());
    const spawnedIds = runtime.listAgentIds();
    expect(spawnedIds).toHaveLength(1);

    // A second orchestrator that shares the spawned delegate's id forces an
    // empty candidate pool, so another default delegate would be required.
    const secondOrchestrator = new Agent({
      id: spawnedIds[0] ?? "delegate",
      role: "Orchestrator",
      instructions: "Coordinate more work.",
      model,
      behavior: "orchestrator"
    });
    const secondTools = runtime.createOrchestratorTools(secondOrchestrator);

    await expect(
      secondTools.delegate_task?.execute({ task: "Handle the follow-up." }, createToolContext())
    ).rejects.toThrow(/Spawn limit reached/);
  });
});
