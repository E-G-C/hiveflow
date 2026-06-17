import type { ActionPolicy, ActionProposal, ActionRecord, RollbackRecord } from "./agent.js";

/**
 * Serialize a value to JSON without throwing on circular references, BigInt
 * values, or functions.
 *
 * - Circular references are dropped. Only true ancestor cycles are removed;
 *   shared sibling references are preserved.
 * - BigInt values are converted to their decimal string representation.
 * - Functions (and `undefined`) are omitted, matching `JSON.stringify`.
 *
 * Returns the literal string `"null"` if serialization fails for any other
 * reason, so callers can always rely on receiving valid JSON.
 */
export function safeSerialize(value: unknown, space?: number): string {
  const ancestors: unknown[] = [];

  function replacer(this: unknown, _key: string, val: unknown): unknown {
    if (typeof val === "bigint") {
      return val.toString();
    }

    if (typeof val === "function") {
      return undefined;
    }

    if (val === null || typeof val !== "object") {
      return val;
    }

    // Trim the ancestor stack back to the holder of the current value so that
    // only genuine ancestors (not already-serialized siblings) are considered.
    while (ancestors.length > 0 && ancestors[ancestors.length - 1] !== this) {
      ancestors.pop();
    }

    if (ancestors.includes(val)) {
      return undefined;
    }

    ancestors.push(val);
    return val;
  }

  try {
    return JSON.stringify(value, replacer, space);
  } catch {
    return "null";
  }
}

/**
 * Deep-clone a value using {@link safeSerialize}. Resilient to circular
 * references, BigInt values, and functions. Primitives and `undefined`/`null`
 * are returned as-is; if cloning fails the original reference is returned so
 * callers never receive a thrown error.
 */
export function safeClone<T>(value: T): T {
  if (value === undefined || value === null) {
    return value;
  }

  if (typeof value !== "object") {
    return value;
  }

  // `safeSerialize` returns the literal "null" only when serialization fails
  // (a non-null object never stringifies to "null" otherwise). In that case
  // fall back to the original reference rather than yielding `null`.
  const serialized = safeSerialize(value);
  if (serialized === "null") {
    return value;
  }

  try {
    return JSON.parse(serialized) as T;
  } catch {
    return value;
  }
}

const ACTION_RECORD_STATUSES = new Set<ActionRecord["status"]>([
  "completed",
  "dry_run",
  "error",
  "rejected"
]);

const ROLLBACK_RECORD_STATUSES = new Set<RollbackRecord["status"]>([
  "completed",
  "error"
]);

const ACTION_POLICIES = new Set<ActionPolicy>([
  "auto",
  "require_approval",
  "dry_run",
  "confirm_on_error"
]);

// Conservative fallbacks for untrusted/persisted values: an unknown record
// status is treated as a failure, and an unknown policy requires approval
// rather than silently auto-executing.
const DEFAULT_ACTION_RECORD_STATUS: ActionRecord["status"] = "error";
const DEFAULT_ROLLBACK_RECORD_STATUS: RollbackRecord["status"] = "error";
const DEFAULT_ACTION_POLICY: ActionPolicy = "require_approval";

function normalizeActionRecordStatus(value: string): ActionRecord["status"] {
  return ACTION_RECORD_STATUSES.has(value as ActionRecord["status"])
    ? (value as ActionRecord["status"])
    : DEFAULT_ACTION_RECORD_STATUS;
}

function normalizeRollbackRecordStatus(value: string): RollbackRecord["status"] {
  return ROLLBACK_RECORD_STATUSES.has(value as RollbackRecord["status"])
    ? (value as RollbackRecord["status"])
    : DEFAULT_ROLLBACK_RECORD_STATUS;
}

function normalizeActionPolicy(value: string): ActionPolicy {
  return ACTION_POLICIES.has(value as ActionPolicy)
    ? (value as ActionPolicy)
    : DEFAULT_ACTION_POLICY;
}

export function normalizeActionProposals(value: unknown): ActionProposal[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((proposal) => normalizeActionProposal(proposal))
    .filter((proposal): proposal is ActionProposal => proposal !== undefined);
}

export function normalizeActionProposal(value: unknown): ActionProposal | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const record = value as Record<string, unknown>;
  const tool = record.tool;
  const toolCallId = record.toolCallId ?? record.tool_call_id;

  if (typeof tool !== "string" || typeof toolCallId !== "string") {
    return undefined;
  }

  return {
    tool,
    arguments: record.arguments,
    toolCallId
  };
}

export function normalizeActionRecords(value: unknown): ActionRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((record) => normalizeActionRecord(record))
    .filter((record): record is ActionRecord => record !== undefined);
}

export function normalizeActionRecord(value: unknown): ActionRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const record = value as Record<string, unknown>;
  const actionId = record.actionId;
  const agentId = record.agentId;
  const tool = record.tool;
  const status = record.status;
  const policy = record.policy;
  const toolCallId = record.toolCallId ?? record.tool_call_id;

  if (
    typeof actionId !== "string"
    || typeof agentId !== "string"
    || typeof tool !== "string"
    || typeof status !== "string"
    || typeof policy !== "string"
    || typeof toolCallId !== "string"
  ) {
    return undefined;
  }

  return {
    actionId,
    agentId,
    tool,
    arguments: record.arguments,
    status: normalizeActionRecordStatus(status),
    policy: normalizeActionPolicy(policy),
    toolCallId,
    ...(record.reversible === true ? { reversible: true } : {}),
    ...(typeof record.rollbackAction === "string" ? { rollbackAction: record.rollbackAction } : {}),
    result: record.result
  };
}

export function normalizeRollbackRecords(value: unknown): RollbackRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((record) => normalizeRollbackRecord(record))
    .filter((record): record is RollbackRecord => record !== undefined);
}

export function normalizeRollbackRecord(value: unknown): RollbackRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const record = value as Record<string, unknown>;
  const rollbackId = record.rollbackId ?? record.rollback_id;
  const agentId = record.agentId;
  const rollbackAction = record.rollbackAction ?? record.rollback_action;
  const status = record.status;

  if (
    typeof rollbackId !== "string"
    || typeof agentId !== "string"
    || typeof rollbackAction !== "string"
    || typeof status !== "string"
  ) {
    return undefined;
  }

  return {
    rollbackId,
    agentId,
    rollbackAction,
    status: normalizeRollbackRecordStatus(status),
    failedActions: normalizeActionRecords(record.failedActions ?? record.failed_actions),
    result: record.result
  };
}

export function normalizeActionErrorRollbackRecord(value: unknown): RollbackRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const details = value as Record<string, unknown>;
  return normalizeRollbackRecord(details.rollback);
}
