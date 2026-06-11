import { readdir, readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { parse as parseYaml } from "yaml";

import type { ActionPolicy, AgentBehavior } from "./agent.js";
import type { ModelDefinition } from "./definition.js";
import type { ModelAdapter } from "./model.js";
import { TeamConfiguration } from "./team.js";
import type { TeamAgentConfiguration, TeamModelReference, TeamWorkflowStep } from "./team.js";
import type { ModelMessage } from "./types.js";
import type { WorkflowData } from "./types.js";

const SUPPORTED_ARCHETYPE_EXTENSIONS = new Set([".json", ".yaml", ".yml"]);
const SUPPORTED_BEHAVIORS = new Set<AgentBehavior>([
  "llm_only",
  "tool_user",
  "orchestrator",
  "human_gate",
  "action_executor"
]);
const SUPPORTED_ACTION_POLICIES = new Set<ActionPolicy>([
  "auto",
  "require_approval",
  "dry_run",
  "confirm_on_error"
]);
const DEFAULT_LLM_TEAM_GENERATION_ATTEMPTS = 3;

export interface ArchetypeDefinition {
  id: string;
  role: string;
  instructions: string;
  model?: TeamModelReference;
  behavior?: AgentBehavior;
  prompt?: string;
  toolIds?: string[];
  actionPolicy?: ActionPolicy;
  rollbackOnFailure?: boolean;
  rollbackAction?: string;
  temperature?: number;
  maxOutputTokens?: number;
  outputType?: string;
  description?: string;
  tags?: string[];
  modelRequirements?: WorkflowData;
}

export interface TeamGeneratorOptions {
  archetypeLibrary?: ArchetypeLibrary;
}

export interface GenerateTeamOptions {
  taskDescription: string;
  archetypes?: string[];
  model?: TeamModelReference;
  includeReview?: boolean;
  teamName?: string;
  description?: string;
  version?: string;
}

export type CapabilityGapSeverity = "blocking" | "warning";

export interface CapabilityGap {
  resourceType: string;
  resourceId: string;
  severity: CapabilityGapSeverity;
  description: string;
  fallbackStrategy?: string;
}

export interface GenerateTeamFromLLMOptions {
  taskDescription: string;
  llm: ModelAdapter;
  model?: TeamModelReference;
  archetypeLibrary?: ArchetypeLibrary;
  availableTools?: Iterable<string> | Record<string, unknown>;
  autoApprove?: boolean;
}

export interface TeamGenerationResult {
  config: TeamConfiguration;
  capabilityGaps: CapabilityGap[];
  newArchetypes: TeamAgentConfiguration[];
  hasBlockingGaps: boolean;
}

interface GeneratedAgentPlan {
  name: string;
  id: string;
  archetype: ArchetypeDefinition;
  model: TeamModelReference;
}

const BUILT_IN_ARCHETYPES: Record<string, ArchetypeDefinition> = {
  researcher: {
    id: "researcher",
    role: "Deep Researcher",
    instructions:
      "You are a thorough research agent. Search for information, evaluate source quality, and synthesize findings.",
    behavior: "tool_user",
    toolIds: ["web_search"],
    description: "Searches for information, evaluates sources, and synthesizes findings.",
    tags: ["research", "data_collection"],
    modelRequirements: {
      strengths: ["analysis", "reasoning"],
      supportsToolCalling: true
    }
  },
  planner: {
    id: "planner",
    role: "Task Planner",
    instructions:
      "You are a task planner. Decompose the given task into 4-6 independent sub-tasks that can be executed in parallel. Each sub-task should be self-contained.",
    behavior: "orchestrator",
    description: "Decomposes a task into parallelizable work units.",
    tags: ["planning", "coordination"]
  },
  writer: {
    id: "writer",
    role: "Content Writer",
    instructions:
      "You are a professional writer. Transform findings into clear, well-structured deliverables.",
    behavior: "llm_only",
    description: "Turns findings into polished written output.",
    tags: ["writing", "communication"]
  },
  reviewer: {
    id: "reviewer",
    role: "Quality Reviewer",
    instructions:
      "You are a quality reviewer. Evaluate deliverables for accuracy, completeness, and clarity. Explicitly say whether the result is accepted or rejected.",
    behavior: "llm_only",
    description: "Checks output quality and drives revision loops.",
    tags: ["review", "quality"]
  },
  editor: {
    id: "editor",
    role: "Task Editor",
    instructions:
      "You are a task editor. Break down complex tasks into clear sub-tasks and coordinate agent workflows.",
    behavior: "orchestrator",
    description: "Coordinates workflows and refines task structure.",
    tags: ["editing", "coordination"]
  },
  human_reviewer: {
    id: "human_reviewer",
    role: "Human Review Gate",
    instructions: "Pause for human review and approval.",
    behavior: "human_gate",
    description: "Pauses the workflow so a human can approve or reject progress.",
    tags: ["review", "human_in_the_loop"]
  }
};

export class ArchetypeLibrary {
  private readonly archetypes = new Map<string, ArchetypeDefinition>();

  listArchetypes(): string[] {
    return Array.from(this.archetypes.keys()).sort();
  }

  get(name: string): ArchetypeDefinition | undefined {
    const archetype = this.archetypes.get(name);
    return archetype ? cloneArchetypeValue(archetype) : undefined;
  }

  register(name: string, archetype: unknown): this {
    this.archetypes.set(name, normalizeArchetypeDefinition(archetype, name));
    return this;
  }

  merge(library: ArchetypeLibrary): this {
    for (const name of library.listArchetypes()) {
      const archetype = library.get(name);
      if (archetype) {
        this.register(name, archetype);
      }
    }

    return this;
  }

  static fromBuiltIns(): ArchetypeLibrary {
    const library = new ArchetypeLibrary();

    for (const [name, archetype] of Object.entries(BUILT_IN_ARCHETYPES)) {
      library.register(name, archetype);
    }

    return library;
  }

  static async default(): Promise<ArchetypeLibrary> {
    const library = ArchetypeLibrary.fromBuiltIns();
    const directory = fileURLToPath(new URL("../templates/archetypes", import.meta.url));

    try {
      library.merge(await ArchetypeLibrary.fromDirectory(directory));
    } catch (error) {
      if (!isDirectoryMissingError(error)) {
        throw error;
      }
    }

    return library;
  }

  static async fromDirectory(path: string): Promise<ArchetypeLibrary> {
    const library = new ArchetypeLibrary();
    const entries = await readdir(path, { withFileTypes: true });

    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      if (!entry.isFile()) {
        continue;
      }

      const extension = extname(entry.name).toLowerCase();
      if (!SUPPORTED_ARCHETYPE_EXTENSIONS.has(extension)) {
        continue;
      }

      const name = stripFileExtension(entry.name);
      const archetype = await loadArchetypeFile(join(path, entry.name), name);
      library.register(name, archetype);
    }

    return library;
  }
}

export class TeamGenerator {
  private readonly archetypeLibrary: ArchetypeLibrary;

  constructor(options: TeamGeneratorOptions = {}) {
    this.archetypeLibrary = options.archetypeLibrary ?? ArchetypeLibrary.fromBuiltIns();
  }

  generateTeam(options: GenerateTeamOptions): TeamConfiguration {
    const taskDescription = readRequiredString(options.taskDescription, "GenerateTeamOptions.taskDescription");
    const archetypeNames = resolveGeneratedArchetypes(
      options.archetypes,
      options.includeReview ?? true
    );
    const counts = countOccurrences(archetypeNames);
    const seenCounts = new Map<string, number>();
    const plans = archetypeNames.map((name) => {
      const archetype = this.archetypeLibrary.get(name);
      if (!archetype) {
        throw new Error(`Archetype '${name}' was not found in the available ArchetypeLibrary.`);
      }

      const occurrence = (seenCounts.get(name) ?? 0) + 1;
      seenCounts.set(name, occurrence);

      return {
        name,
        id: (counts.get(name) ?? 0) > 1 ? `${name}_${occurrence}` : name,
        archetype,
        model: archetype.model ?? options.model ?? "$SMART_LLM"
      } satisfies GeneratedAgentPlan;
    });

    return new TeamConfiguration({
      teamName: options.teamName ?? buildGeneratedTeamName(taskDescription),
      ...(typeof options.version === "string" ? { version: options.version } : {}),
      description: options.description ?? taskDescription,
      agents: plans.map((plan) => buildGeneratedTeamAgent(plan)),
      workflow: {
        steps: plans.map((plan, index) => buildGeneratedWorkflowStep(plans, plan, index))
      }
    });
  }

  async generateTeamFromLLM(
    options: GenerateTeamFromLLMOptions
  ): Promise<TeamGenerationResult> {
    const taskDescription = readRequiredString(
      options.taskDescription,
      "GenerateTeamFromLLMOptions.taskDescription"
    );
    const archetypeLibrary = options.archetypeLibrary ?? this.archetypeLibrary;
    const availableToolIds = normalizeAvailableToolIds(options.availableTools);
    const prompt = buildLLMTeamGenerationPrompt({
      taskDescription,
      archetypeLibrary,
      availableToolIds,
      defaultModel: options.model ?? "$SMART_LLM"
    });
    let previousCandidate: unknown;
    let lastError: unknown;

    for (let attempt = 0; attempt < DEFAULT_LLM_TEAM_GENERATION_ATTEMPTS; attempt += 1) {
      const messages: ModelMessage[] = [
        {
          role: "user",
          content: prompt
        }
      ];

      if (attempt > 0) {
        messages.push(
          {
            role: "assistant",
            content: formatGeneratedTeamCandidate(previousCandidate)
          },
          {
            role: "user",
            content: buildLLMTeamGenerationRepairPrompt(lastError)
          }
        );
      }

      const invocation = await options.llm.generate({ messages });
      previousCandidate = invocation.output ?? invocation.text;

      try {
        const config = TeamConfiguration.parse(parseGeneratedTeamConfiguration(previousCandidate));
        const capabilityGaps = detectCapabilityGaps(config, availableToolIds);
        const result: TeamGenerationResult = {
          config,
          capabilityGaps,
          newArchetypes: detectNewArchetypes(config, archetypeLibrary),
          hasBlockingGaps: capabilityGaps.some((gap) => gap.severity === "blocking")
        };

        if (options.autoApprove === true && result.hasBlockingGaps) {
          const blockingGapDetails = result.capabilityGaps
            .filter((gap) => gap.severity === "blocking")
            .map((gap) => `${gap.resourceType}:${gap.resourceId} (${gap.severity})`)
            .join("; ");

          throw new Error(`Cannot auto-approve team with blocking gaps: ${blockingGapDetails}`);
        }

        return result;
      } catch (error) {
        lastError = error;
      }
    }

    throw new Error(
      `LLM team generation failed validation after ${DEFAULT_LLM_TEAM_GENERATION_ATTEMPTS} attempts: ${formatErrorMessage(lastError)}`
    );
  }
}

async function loadArchetypeFile(
  filePath: string,
  defaultName: string
): Promise<ArchetypeDefinition> {
  const extension = extname(filePath).toLowerCase();
  const raw = await readFile(filePath, "utf8");

  if (extension === ".json") {
    return normalizeArchetypeDefinition(JSON.parse(raw) as unknown, defaultName);
  }

  if (extension === ".yaml" || extension === ".yml") {
    return normalizeArchetypeDefinition(parseYaml(raw), defaultName);
  }

  throw new Error(`Unsupported archetype file '${filePath}'.`);
}

function normalizeArchetypeDefinition(
  value: unknown,
  fallbackId?: string
): ArchetypeDefinition {
  const record = asRecord(value, "ArchetypeDefinition");
  const behaviorValue = record.behavior ?? record.behaviorType ?? record.behavior_type;
  const toolsValue = record.toolIds ?? record.tool_ids ?? record.tools;
  const actionPolicyValue = record.actionPolicy ?? record.action_policy;
  const tagsValue = record.tags;
  const modelRequirementsValue = record.modelRequirements ?? record.model_requirements;
  const maxOutputTokensValue =
    record.maxOutputTokens ?? record.max_output_tokens ?? record.maxTokens ?? record.max_tokens;

  return {
    id: readRequiredString(record.id ?? fallbackId, "ArchetypeDefinition.id"),
    role: readRequiredString(record.role, "ArchetypeDefinition.role"),
    instructions: readRequiredString(
      record.instructions ?? record.systemPrompt ?? record.system_prompt,
      "ArchetypeDefinition.instructions"
    ),
    ...(record.model !== undefined ? { model: normalizeTeamModelReference(record.model) } : {}),
    ...(typeof behaviorValue === "string" ? { behavior: normalizeAgentBehavior(behaviorValue) } : {}),
    ...(typeof record.prompt === "string" ? { prompt: record.prompt } : {}),
    ...(toolsValue ? { toolIds: normalizeStringArray(toolsValue, "ArchetypeDefinition.toolIds") } : {}),
    ...(typeof actionPolicyValue === "string"
      ? { actionPolicy: normalizeActionPolicy(actionPolicyValue) }
      : {}),
    ...((record.rollbackOnFailure ?? record.rollback_on_failure) === true
      ? { rollbackOnFailure: true }
      : {}),
    ...(typeof (record.rollbackAction ?? record.rollback_action) === "string"
      ? { rollbackAction: String(record.rollbackAction ?? record.rollback_action) }
      : {}),
    ...(typeof record.temperature === "number" ? { temperature: record.temperature } : {}),
    ...(typeof maxOutputTokensValue === "number"
      ? { maxOutputTokens: maxOutputTokensValue as number }
      : {}),
    ...(typeof (record.outputType ?? record.output_type) === "string"
      ? { outputType: String(record.outputType ?? record.output_type) }
      : {}),
    ...(typeof record.description === "string" ? { description: record.description } : {}),
    ...(Array.isArray(tagsValue)
      ? { tags: normalizeStringArray(tagsValue, "ArchetypeDefinition.tags") }
      : {}),
    ...(modelRequirementsValue && typeof modelRequirementsValue === "object"
      ? { modelRequirements: cloneArchetypeValue(modelRequirementsValue) as WorkflowData }
      : {})
  };
}

function normalizeTeamModelReference(value: unknown): TeamModelReference {
  if (typeof value === "string") {
    return value;
  }

  return normalizeModelDefinition(value, "ArchetypeDefinition.model");
}

function normalizeModelDefinition(value: unknown, path: string): ModelDefinition {
  const record = asRecord(value, path);
  return {
    kind: readRequiredString(record.kind, `${path}.kind`),
    ...(record.options && typeof record.options === "object"
      ? { options: cloneArchetypeValue(record.options) as WorkflowData }
      : {})
  };
}

function resolveGeneratedArchetypes(
  archetypes: string[] | undefined,
  includeReview: boolean
): string[] {
  const selected = Array.isArray(archetypes) && archetypes.length > 0
    ? [...archetypes]
    : ["researcher", "writer"];

  if (includeReview && !selected.includes("reviewer")) {
    selected.push("reviewer");
  }

  return selected;
}

function buildGeneratedTeamName(taskDescription: string): string {
  const summary = taskDescription.trim().slice(0, 50);
  return summary.length > 0 ? `Generated Team: ${summary}` : "Generated Team";
}

function buildGeneratedTeamAgent(plan: GeneratedAgentPlan): TeamAgentConfiguration {
  const { archetype } = plan;

  return {
    id: plan.id,
    role: archetype.role,
    instructions: archetype.instructions,
    model: cloneArchetypeValue(plan.model),
    ...(archetype.behavior ? { behavior: archetype.behavior } : {}),
    ...(archetype.prompt ? { prompt: archetype.prompt } : {}),
    ...(archetype.toolIds ? { toolIds: [...archetype.toolIds] } : {}),
    ...(archetype.actionPolicy ? { actionPolicy: archetype.actionPolicy } : {}),
    ...(archetype.rollbackOnFailure === true ? { rollbackOnFailure: true } : {}),
    ...(archetype.rollbackAction ? { rollbackAction: archetype.rollbackAction } : {}),
    ...(typeof archetype.temperature === "number" ? { temperature: archetype.temperature } : {}),
    ...(typeof archetype.maxOutputTokens === "number"
      ? { maxOutputTokens: archetype.maxOutputTokens }
      : {}),
    ...(archetype.outputType ? { outputType: archetype.outputType } : {})
  };
}

function buildGeneratedWorkflowStep(
  plans: GeneratedAgentPlan[],
  plan: GeneratedAgentPlan,
  index: number
): TeamWorkflowStep {
  const previousPlan = index > 0 ? plans[index - 1] : undefined;
  const nextPlan = index < plans.length - 1 ? plans[index + 1] : undefined;

  if (previousPlan?.archetype.behavior === "orchestrator") {
    return {
      agent: plan.id,
      type: "parallel_fan_out",
      ...(nextPlan ? { next: nextPlan.id } : {})
    };
  }

  if (plan.archetype.behavior === "human_gate") {
    return {
      agent: plan.id,
      type: "human_gate",
      ...(nextPlan ? { next: nextPlan.id } : {})
    };
  }

  if (plan.name === "reviewer" && previousPlan) {
    return {
      agent: plan.id,
      type: "conditional",
      ...(nextPlan ? { nextOnAccept: nextPlan.id } : {}),
      nextOnReject: previousPlan.id
    };
  }

  return {
    agent: plan.id,
    type: "sequential",
    ...(nextPlan ? { next: nextPlan.id } : {})
  };
}

function buildLLMTeamGenerationPrompt(options: {
  taskDescription: string;
  archetypeLibrary: ArchetypeLibrary;
  availableToolIds: Set<string>;
  defaultModel: TeamModelReference;
}): string {
  const archetypeExamples = options.archetypeLibrary
    .listArchetypes()
    .slice(0, 6)
    .map((name) => {
      const archetype = options.archetypeLibrary.get(name);
      if (!archetype) {
        return undefined;
      }

      const tools = archetype.toolIds && archetype.toolIds.length > 0
        ? ` tools=[${archetype.toolIds.join(", ")}]`
        : "";

      return `  - ${name}: ${archetype.role} (${archetype.behavior ?? "llm_only"})${tools}`;
    })
    .filter((entry): entry is string => typeof entry === "string")
    .join("\n");
  const availableTools = Array.from(options.availableToolIds)
    .sort((left, right) => left.localeCompare(right))
    .map((toolId) => `  - ${toolId}`)
    .join("\n");

  return [
    "Generate a multi-agent team configuration for the task below.",
    "",
    `Task: ${options.taskDescription}`,
    "",
    "Known archetypes (use these as examples, not as hard constraints):",
    archetypeExamples || "  (none)",
    "",
    "Available tools (only reference toolIds from this list):",
    availableTools || "  (none)",
    "",
    `Default agent model reference: ${formatModelReferenceForPrompt(options.defaultModel)}`,
    "",
    "Respond with ONLY a JSON object compatible with TeamConfiguration.",
    "Required top-level fields: teamName, description, agents, workflow.",
    "Each agent must include: id, role, instructions, behavior, model.",
    "Each workflow step must include agent and type.",
    "Every workflow.steps[i].agent must exactly match one of the ids declared in agents.",
    "Use toolIds only when a tool is required. Omit toolIds or use [] when no tool is needed.",
    `Allowed agent behaviors: ${Array.from(SUPPORTED_BEHAVIORS).join(", ")}.`,
    "Allowed workflow step types: sequential, parallel_fan_out, conditional, human_gate, gated, sub_workflow.",
    "Use explicit transitions through next, nextOnAccept, and nextOnReject when needed.",
    "Do not wrap the JSON in markdown fences or explanatory text."
  ].join("\n");
}

function formatModelReferenceForPrompt(value: TeamModelReference): string {
  return typeof value === "string" ? JSON.stringify(value) : JSON.stringify(value, null, 2);
}

function parseGeneratedTeamConfiguration(value: unknown): Record<string, unknown> {
  if (isRecordLike(value)) {
    return cloneArchetypeValue(value);
  }

  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error("LLM team generation returned an empty response.");
  }

  for (const candidate of buildJsonCandidates(value)) {
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (isRecordLike(parsed)) {
        return parsed;
      }
    } catch {
      continue;
    }
  }

  throw new Error("LLM team generation did not return a valid JSON object.");
}

function formatGeneratedTeamCandidate(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function buildLLMTeamGenerationRepairPrompt(error: unknown): string {
  return [
    "The previous TeamConfiguration response was invalid.",
    `Validation error: ${formatErrorMessage(error)}`,
    "Return ONLY a corrected JSON object compatible with TeamConfiguration.",
    "Do not change the task intent.",
    "Make sure each workflow.steps[i].agent is a non-empty string and exactly matches one of the declared agent ids.",
    "Use only the available toolIds from the original prompt.",
    "Do not wrap the JSON in markdown fences or explanatory text."
  ].join("\n");
}

function buildJsonCandidates(value: string): string[] {
  const trimmed = value.trim();
  const strippedFence = trimCodeFence(trimmed);
  const candidates = new Set<string>([trimmed, strippedFence]);
  const objectStart = strippedFence.indexOf("{");
  const objectEnd = strippedFence.lastIndexOf("}");

  if (objectStart >= 0 && objectEnd > objectStart) {
    candidates.add(strippedFence.slice(objectStart, objectEnd + 1).trim());
  }

  return Array.from(candidates).filter((candidate) => candidate.length > 0);
}

function trimCodeFence(value: string): string {
  return value.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "").trim();
}

function formatErrorMessage(error: unknown): string {
  if (error instanceof Error && typeof error.message === "string" && error.message.length > 0) {
    return error.message;
  }

  return String(error ?? "Unknown error");
}

function detectCapabilityGaps(
  config: TeamConfiguration,
  availableToolIds: Set<string>
): CapabilityGap[] {
  const capabilityGaps: CapabilityGap[] = [];

  for (const agent of config.agents) {
    for (const toolId of agent.toolIds ?? []) {
      if (!toolId || availableToolIds.has(toolId)) {
        continue;
      }

      capabilityGaps.push({
        resourceType: "tool",
        resourceId: toolId,
        severity: "blocking",
        description: `Agent '${agent.id}' requires tool '${toolId}' which is not registered`,
        fallbackStrategy: `Remove tool requirement or register '${toolId}'`
      });
    }
  }

  return capabilityGaps;
}

function detectNewArchetypes(
  config: TeamConfiguration,
  archetypeLibrary: ArchetypeLibrary
): TeamAgentConfiguration[] {
  const knownArchetypes = new Set(archetypeLibrary.listArchetypes());

  return config.agents.filter((agent) => !knownArchetypes.has(agent.id));
}

function normalizeAvailableToolIds(
  value: Iterable<string> | Record<string, unknown> | undefined
): Set<string> {
  if (!value) {
    return new Set();
  }

  if (isRecordLike(value) && !(Symbol.iterator in value)) {
    return new Set(Object.keys(value));
  }

  return new Set(
    Array.from(value as Iterable<string>, (toolId) =>
      readRequiredString(toolId, "GenerateTeamFromLLMOptions.availableTools[]")
    )
  );
}

function isRecordLike(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeAgentBehavior(value: string): AgentBehavior {
  if (!SUPPORTED_BEHAVIORS.has(value as AgentBehavior)) {
    throw new Error(`Unsupported agent behavior '${value}'.`);
  }

  return value as AgentBehavior;
}

function normalizeActionPolicy(value: string): ActionPolicy {
  if (!SUPPORTED_ACTION_POLICIES.has(value as ActionPolicy)) {
    throw new Error(`Unsupported action policy '${value}'.`);
  }

  return value as ActionPolicy;
}

function normalizeStringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${path} must be an array of strings.`);
  }

  return value.map((entry, index) => readRequiredString(entry, `${path}[${index}]`));
}

function readRequiredString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${path} must be a non-empty string.`);
  }

  return value;
}

function asRecord(value: unknown, path: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${path} must be an object.`);
  }

  return value as Record<string, unknown>;
}

function countOccurrences(values: string[]): Map<string, number> {
  const counts = new Map<string, number>();

  for (const value of values) {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }

  return counts;
}

function stripFileExtension(value: string): string {
  const extension = extname(value);
  return extension.length > 0 ? value.slice(0, -extension.length) : value;
}

function isDirectoryMissingError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error
    ? (error as { code?: unknown }).code === "ENOENT"
    : false;
}

function cloneArchetypeValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}