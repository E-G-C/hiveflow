import { randomUUID } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join, resolve, sep } from "node:path";

import type { WorkflowDefinition } from "./definition.js";
import type { WorkflowResult } from "./workflow.js";
import { safeClone, safeSerialize } from "./internal.js";

const CHECKPOINT_VERSION = "1";

export class CheckpointError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "CheckpointError";
  }
}

export interface WorkflowCheckpoint {
  sessionId: string;
  checkpointId: string;
  createdAt: number;
  pausedResult: WorkflowResult;
  workflowDefinition?: WorkflowDefinition;
  version: string;
}

export interface CheckpointStorage {
  save(checkpoint: WorkflowCheckpoint): Promise<string>;
  load(sessionId: string, checkpointId?: string): Promise<WorkflowCheckpoint | undefined>;
  delete(sessionId: string): Promise<void>;
  listSessions(): Promise<string[]>;
  listCheckpoints(sessionId: string): Promise<WorkflowCheckpoint[]>;
}

export interface CreateWorkflowCheckpointOptions {
  sessionId: string;
  pausedResult: WorkflowResult;
  checkpointId?: string;
  createdAt?: number;
  workflowDefinition?: WorkflowDefinition;
}

export function createWorkflowCheckpoint(
  options: CreateWorkflowCheckpointOptions
): WorkflowCheckpoint {
  if (options.pausedResult.status !== "paused") {
    throw new CheckpointError("Workflow checkpoints can only be created from paused results.");
  }

  return {
    sessionId: options.sessionId,
    checkpointId: options.checkpointId ?? randomUUID(),
    createdAt: options.createdAt ?? Date.now(),
    pausedResult: cloneCheckpointValue(options.pausedResult),
    ...(options.workflowDefinition
      ? {
          workflowDefinition: cloneCheckpointValue(options.workflowDefinition)
        }
      : {}),
    version: CHECKPOINT_VERSION
  };
}

export class InMemoryCheckpointStorage implements CheckpointStorage {
  private readonly checkpoints = new Map<string, Map<string, WorkflowCheckpoint>>();

  async save(checkpoint: WorkflowCheckpoint): Promise<string> {
    const sessionCheckpoints = this.checkpoints.get(checkpoint.sessionId) ?? new Map();
    sessionCheckpoints.set(checkpoint.checkpointId, cloneCheckpointValue(checkpoint));
    this.checkpoints.set(checkpoint.sessionId, sessionCheckpoints);
    return checkpoint.checkpointId;
  }

  async load(
    sessionId: string,
    checkpointId?: string
  ): Promise<WorkflowCheckpoint | undefined> {
    const sessionCheckpoints = this.checkpoints.get(sessionId);
    if (!sessionCheckpoints || sessionCheckpoints.size === 0) {
      return undefined;
    }

    if (checkpointId) {
      const checkpoint = sessionCheckpoints.get(checkpointId);
      return checkpoint ? cloneCheckpointValue(checkpoint) : undefined;
    }

    const checkpoints = Array.from(sessionCheckpoints.values()).sort(
      (left, right) => left.createdAt - right.createdAt
    );
    const latest = checkpoints.at(-1);
    return latest ? cloneCheckpointValue(latest) : undefined;
  }

  async delete(sessionId: string): Promise<void> {
    this.checkpoints.delete(sessionId);
  }

  async listSessions(): Promise<string[]> {
    return Array.from(this.checkpoints.keys()).sort();
  }

  async listCheckpoints(sessionId: string): Promise<WorkflowCheckpoint[]> {
    const sessionCheckpoints = this.checkpoints.get(sessionId);
    if (!sessionCheckpoints) {
      return [];
    }

    return Array.from(sessionCheckpoints.values())
      .sort((left, right) => left.createdAt - right.createdAt)
      .map((checkpoint) => cloneCheckpointValue(checkpoint));
  }
}

export class FileCheckpointStorage implements CheckpointStorage {
  constructor(private readonly directory = ".hiveflow/checkpoints") {}

  async save(checkpoint: WorkflowCheckpoint): Promise<string> {
    const sessionDirectory = this.getSessionDirectory(checkpoint.sessionId);
    const path = this.getCheckpointPath(checkpoint.sessionId, checkpoint.checkpointId);
    const temporaryPath = `${path}.${randomUUID()}.tmp`;

    try {
      await mkdir(sessionDirectory, { recursive: true });
      await writeFile(temporaryPath, safeSerialize(checkpoint, 2), "utf8");
      await rename(temporaryPath, path);
      return checkpoint.checkpointId;
    } catch (error) {
      throw new CheckpointError(
        `Failed to save checkpoint '${checkpoint.checkpointId}' for session '${checkpoint.sessionId}'.`,
        { cause: error }
      );
    }
  }

  async load(
    sessionId: string,
    checkpointId?: string
  ): Promise<WorkflowCheckpoint | undefined> {
    if (checkpointId) {
      const path = this.getCheckpointPath(sessionId, checkpointId);

      try {
        return await this.readCheckpoint(path);
      } catch (error) {
        if (isMissingPathError(error)) {
          return undefined;
        }

        throw error;
      }
    }

    const checkpoints = await this.listCheckpoints(sessionId);
    return checkpoints.at(-1);
  }

  async delete(sessionId: string): Promise<void> {
    await rm(this.getSessionDirectory(sessionId), { recursive: true, force: true });
  }

  async listSessions(): Promise<string[]> {
    try {
      const entries = await readdir(this.directory, { withFileTypes: true });
      const sessionIds = new Set<string>();

      for (const entry of entries) {
        if (!entry.isDirectory()) {
          continue;
        }

        const checkpoints = await this.listCheckpoints(entry.name);
        const firstCheckpoint = checkpoints[0];
        if (firstCheckpoint) {
          sessionIds.add(firstCheckpoint.sessionId);
        }
      }

      return Array.from(sessionIds).sort();
    } catch (error) {
      if (isMissingPathError(error)) {
        return [];
      }

      throw new CheckpointError("Failed to list checkpoint sessions.", { cause: error });
    }
  }

  async listCheckpoints(sessionId: string): Promise<WorkflowCheckpoint[]> {
    try {
      const sessionDirectory = this.getSessionDirectory(sessionId);
      const entries = await readdir(sessionDirectory, { withFileTypes: true });
      const files = entries.filter(
        (entry) => entry.isFile() && entry.name.endsWith(".json")
      );
      const results = await Promise.allSettled(
        files.map((entry) => this.readCheckpoint(join(sessionDirectory, entry.name)))
      );

      const checkpoints: WorkflowCheckpoint[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          checkpoints.push(result.value);
          return;
        }

        const fileName = files[index]?.name ?? "<unknown>";
        console.warn(
          `Skipping unreadable checkpoint file '${fileName}' for session '${sessionId}': ${describeError(result.reason)}`
        );
      });

      return checkpoints.sort((left, right) => left.createdAt - right.createdAt);
    } catch (error) {
      if (isMissingPathError(error)) {
        return [];
      }

      throw new CheckpointError(
        `Failed to list checkpoints for session '${sessionId}'.`,
        { cause: error }
      );
    }
  }

  private getSessionDirectory(sessionId: string): string {
    const directory = join(this.directory, sanitizeId(sessionId, "session"));
    this.assertWithinRoot(directory);
    return directory;
  }

  private getCheckpointPath(sessionId: string, checkpointId: string): string {
    const path = join(
      this.getSessionDirectory(sessionId),
      `${sanitizeId(checkpointId, "checkpoint")}.json`
    );
    this.assertWithinRoot(path);
    return path;
  }

  private assertWithinRoot(candidate: string): void {
    const root = resolve(this.directory);
    const resolved = resolve(candidate);
    if (resolved !== root && !resolved.startsWith(root + sep)) {
      throw new CheckpointError(
        `Resolved checkpoint path '${resolved}' escapes the storage root '${root}'.`
      );
    }
  }

  private async readCheckpoint(path: string): Promise<WorkflowCheckpoint> {
    try {
      const raw = await readFile(path, "utf8");
      return normalizeCheckpoint(JSON.parse(raw) as WorkflowCheckpoint);
    } catch (error) {
      if (error instanceof CheckpointError) {
        throw error;
      }

      throw new CheckpointError(`Failed to read checkpoint file '${path}'.`, { cause: error });
    }
  }
}

function normalizeCheckpoint(checkpoint: WorkflowCheckpoint): WorkflowCheckpoint {
  if (!checkpoint.sessionId || !checkpoint.checkpointId || !checkpoint.pausedResult) {
    throw new CheckpointError("Checkpoint payload is missing required fields.");
  }

  if (checkpoint.pausedResult.status !== "paused") {
    throw new CheckpointError("Checkpoint payload must contain a paused workflow result.");
  }

  return cloneCheckpointValue({
    ...checkpoint,
    version: checkpoint.version ?? CHECKPOINT_VERSION
  });
}

function sanitizeId(value: string, kind: "session" | "checkpoint"): string {
  const sanitized = value.replaceAll(/[^a-zA-Z0-9._-]/g, "_");
  if (sanitized.length === 0 || sanitized === "." || sanitized === "..") {
    throw new CheckpointError(
      `Invalid ${kind} id '${value}' resolves to an unsafe path segment.`
    );
  }

  return sanitized;
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}

function isMissingPathError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: string }).code === "ENOENT"
  );
}

function cloneCheckpointValue<T>(value: T): T {
  return safeClone(value);
}