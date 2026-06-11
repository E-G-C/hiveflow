import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

import type { ActionPolicy, AgentBehavior } from "./agent.js";
import type { CollaborationBudgetPolicy, CollaborationConfig } from "./collaboration.js";
import type { AgentDefinition, ModelDefinition, WorkflowDefinition } from "./definition.js";
import type { WorkflowData } from "./types.js";
import type { WorkflowStep, WorkflowStepType } from "./workflow.js";

type ParallelItemSource = "parallelItems" | "parallel_items" | "taskData" | "task_data";

type WorkflowStateMapping = Record<string, string>;

const SUPPORTED_TEAM_EXTENSIONS = new Set([".json", ".yaml", ".yml"]);
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

export type TeamModelReference = string | ModelDefinition;

export type ModelReferenceResolver = (
  reference: string,
  context: { teamName: string; agentId: string }
) => ModelDefinition;

export interface TeamAgentConfiguration {
  id: string;
  role: string;
  instructions: string;
  model: TeamModelReference;
  behavior?: AgentBehavior;
  prompt?: string;
  toolIds?: string[];
  actionPolicy?: ActionPolicy;
  rollbackOnFailure?: boolean;
  rollbackAction?: string;
  temperature?: number;
  maxOutputTokens?: number;
  outputType?: string;
}

export interface TeamStateSchemaAgentIo {
  reads?: string[];
  writes?: string[];
}

export interface TeamStateSchema {
  requiredKeys?: string[];
  agentIo?: Record<string, TeamStateSchemaAgentIo>;
}

export interface TeamCollaborationConfiguration {
  enabled?: boolean;
  maxDelegationDepth?: number;
  maxSpawnedAgents?: number;
  allowRecursiveOrchestrators?: boolean;
  delegationTimeoutSeconds?: number;
  budgetPolicy?: CollaborationBudgetPolicy;
}

export interface TeamWorkflowStep {
  id?: string;
  agent: string;
  type: WorkflowStepType;
  team?: string;
  inputMapping?: WorkflowStateMapping;
  outputMapping?: WorkflowStateMapping;
  next?: string | null;
  nextOnAccept?: string | null;
  nextOnReject?: string | null;
  source?: ParallelItemSource;
  maxIterations?: number;
  gate?: string;
  gateDescription?: string;
}

export interface TeamWorkflowConfiguration {
  steps: TeamWorkflowStep[];
}

export interface TeamConfigurationData {
  teamName: string;
  version?: string;
  description?: string;
  collaboration?: TeamCollaborationConfiguration;
  agents: TeamAgentConfiguration[];
  workflow: TeamWorkflowConfiguration;
  stateSchema?: TeamStateSchema;
  subWorkflows?: Record<string, TeamConfiguration>;
}

export interface TeamDefinitionBuildOptions {
  teamLibrary?: TeamLibrary;
  modelResolver?: ModelReferenceResolver;
  availableTools?: Iterable<string> | Record<string, unknown>;
}

interface BuildWorkflowDefinitionOptions extends TeamDefinitionBuildOptions {
  resolutionPath: string[];
}

interface CompiledTeamStep {
  id: string;
  step: TeamWorkflowStep;
}

export class TeamConfiguration {
  private readonly data: TeamConfigurationData;

  constructor(data: unknown) {
    this.data = normalizeTeamConfigurationData(data);
  }

  static parse(data: unknown): TeamConfiguration {
    return new TeamConfiguration(data);
  }

  static async fromFile(filePath: string): Promise<TeamConfiguration> {
    const extension = extname(filePath).toLowerCase();
    if (extension === ".json") {
      return this.fromJsonFile(filePath);
    }

    if (extension === ".yaml" || extension === ".yml") {
      return this.fromYamlFile(filePath);
    }

    throw new Error(
      `Unsupported team configuration file '${filePath}'. Expected one of: ${Array.from(SUPPORTED_TEAM_EXTENSIONS).join(", ")}.`
    );
  }

  static async fromJsonFile(filePath: string): Promise<TeamConfiguration> {
    const raw = await readFile(filePath, "utf8");
    return new TeamConfiguration(JSON.parse(raw) as unknown);
  }

  static async fromYamlFile(filePath: string): Promise<TeamConfiguration> {
    const raw = await readFile(filePath, "utf8");
    return new TeamConfiguration(parseYaml(raw));
  }

  get teamName(): string {
    return this.data.teamName;
  }

  get version(): string | undefined {
    return this.data.version;
  }

  get description(): string | undefined {
    return this.data.description;
  }

  get agents(): TeamAgentConfiguration[] {
    return cloneTeamValue(this.data.agents);
  }

  get workflow(): TeamWorkflowConfiguration {
    return cloneTeamValue(this.data.workflow);
  }

  get stateSchema(): TeamStateSchema | undefined {
    return this.data.stateSchema ? cloneTeamValue(this.data.stateSchema) : undefined;
  }

  get subWorkflows(): Record<string, TeamConfiguration> | undefined {
    if (!this.data.subWorkflows) {
      return undefined;
    }

    return Object.fromEntries(
      Object.entries(this.data.subWorkflows).map(([name, configuration]) => [
        name,
        TeamConfiguration.parse(configuration.toJSON())
      ])
    );
  }

  toJSON(): Record<string, unknown> {
    return {
      teamName: this.data.teamName,
      ...(this.data.version ? { version: this.data.version } : {}),
      ...(this.data.description ? { description: this.data.description } : {}),
      ...(this.data.collaboration
        ? { collaboration: cloneTeamValue(this.data.collaboration) }
        : {}),
      agents: this.data.agents.map((agent) => ({
        id: agent.id,
        role: agent.role,
        instructions: agent.instructions,
        model: cloneTeamValue(agent.model),
        ...(agent.behavior ? { behavior: agent.behavior } : {}),
        ...(agent.prompt ? { prompt: agent.prompt } : {}),
        ...(agent.toolIds ? { toolIds: [...agent.toolIds] } : {}),
        ...(agent.actionPolicy ? { actionPolicy: agent.actionPolicy } : {}),
        ...(agent.rollbackOnFailure === true ? { rollbackOnFailure: true } : {}),
        ...(agent.rollbackAction ? { rollbackAction: agent.rollbackAction } : {}),
        ...(typeof agent.temperature === "number" ? { temperature: agent.temperature } : {}),
        ...(typeof agent.maxOutputTokens === "number"
          ? { maxOutputTokens: agent.maxOutputTokens }
          : {}),
        ...(agent.outputType ? { outputType: agent.outputType } : {})
      })),
      workflow: {
        steps: this.data.workflow.steps.map((step) => ({
          ...(step.id ? { id: step.id } : {}),
          agent: step.agent,
          type: step.type,
          ...(step.team ? { team: step.team } : {}),
          ...(step.inputMapping ? { inputMapping: cloneTeamValue(step.inputMapping) } : {}),
          ...(step.outputMapping ? { outputMapping: cloneTeamValue(step.outputMapping) } : {}),
          ...(step.next !== undefined ? { next: step.next } : {}),
          ...(step.nextOnAccept !== undefined ? { nextOnAccept: step.nextOnAccept } : {}),
          ...(step.nextOnReject !== undefined ? { nextOnReject: step.nextOnReject } : {}),
          ...(step.source ? { source: step.source } : {}),
          ...(typeof step.maxIterations === "number" ? { maxIterations: step.maxIterations } : {}),
          ...(step.gate ? { gate: step.gate } : {}),
          ...(step.gateDescription ? { gateDescription: step.gateDescription } : {})
        }))
      },
      ...(this.data.stateSchema ? { stateSchema: cloneTeamValue(this.data.stateSchema) } : {}),
      ...(this.data.subWorkflows
        ? {
            subWorkflows: Object.fromEntries(
              Object.entries(this.data.subWorkflows).map(([name, configuration]) => [
                name,
                configuration.toJSON()
              ])
            )
          }
        : {})
    };
  }

  async saveJson(filePath: string): Promise<void> {
    await mkdir(dirname(filePath), { recursive: true });
    await writeFile(filePath, JSON.stringify(this.toJSON(), null, 2), "utf8");
  }

  async saveYaml(filePath: string): Promise<void> {
    await mkdir(dirname(filePath), { recursive: true });
    await writeFile(filePath, stringifyYaml(this.toJSON()), "utf8");
  }

  toWorkflowDefinition(options: TeamDefinitionBuildOptions = {}): WorkflowDefinition {
    return this.buildWorkflowDefinition({
      ...options,
      resolutionPath: []
    });
  }

  private buildWorkflowDefinition(options: BuildWorkflowDefinitionOptions): WorkflowDefinition {
    const resolutionKey = this.data.teamName;
    if (options.resolutionPath.includes(resolutionKey)) {
      throw new Error(
        `Recursive team reference detected while resolving '${resolutionKey}'. Resolution path: ${[
          ...options.resolutionPath,
          resolutionKey
        ].join(" -> ")}.`
      );
    }

    const nextOptions = {
      ...options,
      resolutionPath: [...options.resolutionPath, resolutionKey]
    };
    const compiledSteps = compileTeamWorkflowSteps(this.data.workflow.steps, this.data.teamName);
    const availableTools = normalizeAvailableTools(options.availableTools);
    const subWorkflowDefinitions: Record<string, WorkflowDefinition> = {};

    for (const [name, configuration] of Object.entries(this.data.subWorkflows ?? {})) {
      subWorkflowDefinitions[name] = configuration.buildWorkflowDefinition(nextOptions);
    }

    for (const step of this.data.workflow.steps) {
      if (step.type !== "sub_workflow" || !step.team || subWorkflowDefinitions[step.team]) {
        continue;
      }

      const referencedConfiguration = options.teamLibrary?.get(step.team);
      if (!referencedConfiguration) {
        throw new Error(
          `Team '${this.data.teamName}' references sub-workflow team '${step.team}' but it was not found inline or in the provided TeamLibrary.`
        );
      }

      subWorkflowDefinitions[step.team] = referencedConfiguration.buildWorkflowDefinition(nextOptions);
    }

    const runtimeAgentOptions = {
      teamName: this.data.teamName
    } as {
      teamName: string;
      modelResolver?: ModelReferenceResolver;
      availableTools?: Set<string>;
    };

    if (options.modelResolver) {
      runtimeAgentOptions.modelResolver = options.modelResolver;
    }

    if (availableTools) {
      runtimeAgentOptions.availableTools = availableTools;
    }

    return {
      id: this.data.teamName,
      steps: compiledSteps,
      agents: this.data.agents.map((agent) =>
        buildRuntimeAgentDefinition(agent, runtimeAgentOptions)
      ),
      ...(this.data.collaboration
        ? { collaboration: cloneTeamValue(this.data.collaboration) as CollaborationConfig }
        : {}),
      ...(Object.keys(subWorkflowDefinitions).length > 0
        ? { subWorkflows: subWorkflowDefinitions }
        : {})
    };
  }
}

export class TeamLibrary {
  private readonly teams = new Map<string, TeamConfiguration>();

  listTeams(): string[] {
    return Array.from(this.teams.keys()).sort();
  }

  get(name: string): TeamConfiguration | undefined {
    const configuration = this.teams.get(name);
    return configuration ? TeamConfiguration.parse(configuration.toJSON()) : undefined;
  }

  register(name: string, config: TeamConfiguration): this {
    this.teams.set(name, TeamConfiguration.parse(config.toJSON()));
    return this;
  }

  static async default(): Promise<TeamLibrary> {
    const directory = fileURLToPath(new URL("../templates/teams", import.meta.url));
    return this.fromDirectory(directory);
  }

  static async fromDirectory(path: string): Promise<TeamLibrary> {
    const library = new TeamLibrary();
    const entries = await readdir(path, { withFileTypes: true });

    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      if (!entry.isFile()) {
        continue;
      }

      const extension = extname(entry.name).toLowerCase();
      if (!SUPPORTED_TEAM_EXTENSIONS.has(extension)) {
        continue;
      }

      const configuration = await TeamConfiguration.fromFile(join(path, entry.name));
      library.register(configuration.teamName, configuration);
    }

    return library;
  }
}

function buildRuntimeAgentDefinition(
  agent: TeamAgentConfiguration,
  options: {
    teamName: string;
    modelResolver?: ModelReferenceResolver;
    availableTools?: Set<string>;
  }
): AgentDefinition {
  validateToolIds(agent, options.availableTools, options.teamName);

  return {
    id: agent.id,
    role: agent.role,
    instructions: agent.instructions,
    model: resolveModelReference(agent.model, options.teamName, agent.id, options.modelResolver),
    ...(agent.behavior ? { behavior: agent.behavior } : {}),
    ...(agent.prompt ? { prompt: agent.prompt } : {}),
    ...(agent.toolIds && agent.toolIds.length > 0 ? { toolIds: [...agent.toolIds] } : {}),
    ...(agent.actionPolicy ? { actionPolicy: agent.actionPolicy } : {}),
    ...(agent.rollbackOnFailure === true ? { rollbackOnFailure: true } : {}),
    ...(agent.rollbackAction ? { rollbackAction: agent.rollbackAction } : {}),
    ...(typeof agent.temperature === "number" ? { temperature: agent.temperature } : {}),
    ...(typeof agent.maxOutputTokens === "number"
      ? { maxOutputTokens: agent.maxOutputTokens }
      : {})
  };
}

function compileTeamWorkflowSteps(
  steps: TeamWorkflowStep[],
  teamName: string
): WorkflowStep[] {
  const agentCounts = countOccurrences(steps.map((step) => step.agent));
  const compiledSteps = steps.map((step, index) => ({
    id: resolveTeamWorkflowStepId(step, index, agentCounts),
    step
  }));
  const seenIds = new Set<string>();
  const references = new Map<string, string>();

  for (const compiled of compiledSteps) {
    if (seenIds.has(compiled.id)) {
      throw new Error(
        `Team '${teamName}' contains duplicate workflow step id '${compiled.id}'. Supply explicit step ids when the same agent appears multiple times.`
      );
    }

    seenIds.add(compiled.id);
    references.set(compiled.id, compiled.id);

    if ((agentCounts.get(compiled.step.agent) ?? 0) === 1) {
      references.set(compiled.step.agent, compiled.id);
    }
  }

  return compiledSteps.map((compiled) => ({
    id: compiled.id,
    agent: compiled.step.agent,
    type: compiled.step.type,
    ...(compiled.step.team ? { team: compiled.step.team } : {}),
    ...(compiled.step.inputMapping ? { inputMapping: cloneTeamValue(compiled.step.inputMapping) } : {}),
    ...(compiled.step.outputMapping ? { outputMapping: cloneTeamValue(compiled.step.outputMapping) } : {}),
    ...resolveWorkflowTargets(compiled.step, teamName, references),
    ...(compiled.step.source ? { source: compiled.step.source } : {}),
    ...(typeof compiled.step.maxIterations === "number"
      ? { maxIterations: compiled.step.maxIterations }
      : {}),
    ...(compiled.step.gate ? { gate: compiled.step.gate } : {}),
    ...(compiled.step.gateDescription ? { gateDescription: compiled.step.gateDescription } : {})
  }));
}

function resolveTeamWorkflowStepId(
  step: TeamWorkflowStep,
  index: number,
  agentCounts: Map<string, number>
): string {
  if (step.id) {
    return step.id;
  }

  if ((agentCounts.get(step.agent) ?? 0) === 1) {
    return step.agent;
  }

  return `${step.agent}_${index + 1}`;
}

function resolveWorkflowTargets(
  step: TeamWorkflowStep,
  teamName: string,
  references: Map<string, string>
): Partial<WorkflowStep> {
  return {
    ...resolveWorkflowTarget("next", step.next, teamName, step.agent, references),
    ...resolveWorkflowTarget(
      "nextOnAccept",
      step.nextOnAccept,
      teamName,
      step.agent,
      references
    ),
    ...resolveWorkflowTarget(
      "nextOnReject",
      step.nextOnReject,
      teamName,
      step.agent,
      references
    )
  };
}

function resolveWorkflowTarget(
  field: "next" | "nextOnAccept" | "nextOnReject",
  target: string | null | undefined,
  teamName: string,
  agentId: string,
  references: Map<string, string>
): Partial<WorkflowStep> {
  if (target === undefined || target === null) {
    return {};
  }

  const resolvedTarget = references.get(target);
  if (!resolvedTarget) {
    throw new Error(
      `Team '${teamName}' step '${agentId}' references unknown workflow target '${target}' for '${field}'. Use an explicit step id when reusing the same agent in multiple steps.`
    );
  }

  return { [field]: resolvedTarget } as Partial<WorkflowStep>;
}

function resolveModelReference(
  reference: TeamModelReference,
  teamName: string,
  agentId: string,
  modelResolver?: ModelReferenceResolver
): ModelDefinition {
  if (typeof reference !== "string") {
    return cloneTeamValue(reference);
  }

  if (!modelResolver) {
    throw new Error(
      `Team '${teamName}' agent '${agentId}' uses string model reference '${reference}' but no modelResolver was provided.`
    );
  }

  return normalizeModelDefinition(
    modelResolver(reference, {
      teamName,
      agentId
    })
  );
}

function validateToolIds(
  agent: TeamAgentConfiguration,
  availableTools: Set<string> | undefined,
  teamName: string
): void {
  if (!availableTools || !agent.toolIds || agent.toolIds.length === 0) {
    return;
  }

  const missingTools = agent.toolIds.filter((toolId) => !availableTools.has(toolId));
  if (missingTools.length > 0) {
    throw new Error(
      `Team '${teamName}' agent '${agent.id}' references unavailable tools: ${missingTools.join(", ")}.`
    );
  }
}

function normalizeAvailableTools(
  value: Iterable<string> | Record<string, unknown> | undefined
): Set<string> | undefined {
  if (!value) {
    return undefined;
  }

  if (typeof value === "object" && !Array.isArray(value) && !(Symbol.iterator in value)) {
    return new Set(Object.keys(value));
  }

  return new Set(value as Iterable<string>);
}

function normalizeTeamConfigurationData(value: unknown): TeamConfigurationData {
  if (value instanceof TeamConfiguration) {
    return normalizeTeamConfigurationData(value.toJSON());
  }

  const record = asRecord(value, "TeamConfiguration");
  const workflow = normalizeTeamWorkflowConfiguration(record.workflow);
  const agents = normalizeTeamAgents(record.agents);
  const stateSchemaValue = record.stateSchema ?? record.state_schema;
  const collaborationValue = record.collaboration;
  const subWorkflowsValue = record.subWorkflows ?? record.sub_workflows;

  const data: TeamConfigurationData = {
    teamName: readRequiredString(record.teamName ?? record.team_name, "TeamConfiguration.teamName"),
    agents,
    workflow,
    ...(typeof record.version === "string" ? { version: record.version } : {}),
    ...(typeof record.description === "string" ? { description: record.description } : {}),
    ...(collaborationValue
      ? { collaboration: normalizeTeamCollaboration(collaborationValue) }
      : {}),
    ...(stateSchemaValue ? { stateSchema: normalizeTeamStateSchema(stateSchemaValue) } : {}),
    ...(subWorkflowsValue ? { subWorkflows: normalizeSubWorkflows(subWorkflowsValue) } : {})
  };

  validateNormalizedTeamConfiguration(data);
  return data;
}

function normalizeTeamWorkflowConfiguration(value: unknown): TeamWorkflowConfiguration {
  const workflowRecord = asRecord(value, "TeamConfiguration.workflow");
  if (!Array.isArray(workflowRecord.steps) || workflowRecord.steps.length === 0) {
    throw new Error("TeamConfiguration.workflow.steps must be a non-empty array.");
  }

  return {
    steps: workflowRecord.steps.map((step, index) => normalizeTeamWorkflowStep(step, index))
  };
}

function normalizeTeamWorkflowStep(value: unknown, index: number): TeamWorkflowStep {
  const record = asRecord(value, `TeamConfiguration.workflow.steps[${index}]`);
  const type = readRequiredString(record.type, `TeamConfiguration.workflow.steps[${index}].type`);
  const maxIterations = record.maxIterations ?? record.max_iterations;

  return {
    ...(typeof record.id === "string" ? { id: record.id } : {}),
    agent: readRequiredString(record.agent, `TeamConfiguration.workflow.steps[${index}].agent`),
    type: normalizeWorkflowStepType(type),
    ...(typeof record.team === "string" ? { team: record.team } : {}),
    ...(record.inputMapping || record.input_mapping
      ? { inputMapping: normalizeStringRecord(record.inputMapping ?? record.input_mapping) }
      : {}),
    ...(record.outputMapping || record.output_mapping
      ? { outputMapping: normalizeStringRecord(record.outputMapping ?? record.output_mapping) }
      : {}),
    ...(record.next !== undefined ? { next: normalizeNullableString(record.next) } : {}),
    ...(record.nextOnAccept !== undefined || record.next_on_accept !== undefined
      ? { nextOnAccept: normalizeNullableString(record.nextOnAccept ?? record.next_on_accept) }
      : {}),
    ...(record.nextOnReject !== undefined || record.next_on_reject !== undefined
      ? { nextOnReject: normalizeNullableString(record.nextOnReject ?? record.next_on_reject) }
      : {}),
    ...(typeof record.source === "string" ? { source: normalizeParallelItemSource(record.source) } : {}),
    ...(typeof maxIterations === "number"
      ? { maxIterations }
      : {}),
    ...(typeof record.gate === "string" ? { gate: record.gate } : {}),
    ...(typeof (record.gateDescription ?? record.gate_description) === "string"
      ? { gateDescription: String(record.gateDescription ?? record.gate_description) }
      : {})
  };
}

function normalizeTeamAgents(value: unknown): TeamAgentConfiguration[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("TeamConfiguration.agents must be a non-empty array.");
  }

  return value.map((agent, index) => normalizeTeamAgent(agent, index));
}

function normalizeTeamAgent(value: unknown, index: number): TeamAgentConfiguration {
  const record = asRecord(value, `TeamConfiguration.agents[${index}]`);
  const behaviorValue = record.behavior ?? record.behaviorType ?? record.behavior_type;
  const toolsValue = record.toolIds ?? record.tool_ids ?? record.tools;
  const actionPolicyValue = record.actionPolicy ?? record.action_policy;

  return {
    id: readRequiredString(record.id, `TeamConfiguration.agents[${index}].id`),
    role: readRequiredString(record.role, `TeamConfiguration.agents[${index}].role`),
    instructions: readRequiredString(
      record.instructions ?? record.systemPrompt ?? record.system_prompt,
      `TeamConfiguration.agents[${index}].instructions`
    ),
    model: normalizeTeamModelReference(record.model, index),
    ...(typeof behaviorValue === "string" ? { behavior: normalizeAgentBehavior(behaviorValue) } : {}),
    ...(typeof record.prompt === "string" ? { prompt: record.prompt } : {}),
    ...(toolsValue ? { toolIds: normalizeStringArray(toolsValue, `TeamConfiguration.agents[${index}].toolIds`) } : {}),
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
    ...(typeof (record.maxOutputTokens ?? record.max_output_tokens ?? record.maxTokens ?? record.max_tokens) === "number"
      ? {
          maxOutputTokens:
            (record.maxOutputTokens ?? record.max_output_tokens ?? record.maxTokens ?? record.max_tokens) as number
        }
      : {}),
    ...(typeof (record.outputType ?? record.output_type) === "string"
      ? { outputType: String(record.outputType ?? record.output_type) }
      : {})
  };
}

function normalizeTeamModelReference(value: unknown, index: number): TeamModelReference {
  if (typeof value === "string") {
    return value;
  }

  return normalizeModelDefinition(value, `TeamConfiguration.agents[${index}].model`);
}

function normalizeModelDefinition(value: unknown, path = "TeamConfiguration.model"): ModelDefinition {
  const record = asRecord(value, path);
  return {
    kind: readRequiredString(record.kind, `${path}.kind`),
    ...(record.options && typeof record.options === "object"
      ? { options: cloneTeamValue(record.options) as WorkflowData }
      : {})
  };
}

function normalizeTeamStateSchema(value: unknown): TeamStateSchema {
  const record = asRecord(value, "TeamConfiguration.stateSchema");
  const requiredKeysValue = record.requiredKeys ?? record.required_keys;
  const agentIoValue = record.agentIo ?? record.agent_io;

  return {
    ...(requiredKeysValue
      ? {
          requiredKeys: normalizeStringArray(requiredKeysValue, "TeamConfiguration.stateSchema.requiredKeys")
        }
      : {}),
    ...(agentIoValue ? { agentIo: normalizeAgentIo(agentIoValue) } : {})
  };
}

function normalizeTeamCollaboration(value: unknown): TeamCollaborationConfiguration {
  const record = asRecord(value, "TeamConfiguration.collaboration");
  const maxDelegationDepth = record.maxDelegationDepth ?? record.max_delegation_depth;
  const maxSpawnedAgents = record.maxSpawnedAgents ?? record.max_spawned_agents;
  const allowRecursiveOrchestrators =
    record.allowRecursiveOrchestrators ?? record.allow_recursive_orchestrators;
  const delegationTimeoutSeconds =
    record.delegationTimeoutSeconds ?? record.delegation_timeout_seconds;

  return {
    ...(typeof record.enabled === "boolean" ? { enabled: record.enabled } : {}),
    ...(typeof maxDelegationDepth === "number" ? { maxDelegationDepth } : {}),
    ...(typeof maxSpawnedAgents === "number" ? { maxSpawnedAgents } : {}),
    ...(typeof allowRecursiveOrchestrators === "boolean"
      ? { allowRecursiveOrchestrators }
      : {}),
    ...(typeof delegationTimeoutSeconds === "number"
      ? { delegationTimeoutSeconds }
      : {}),
    ...(typeof record.budgetPolicy === "string"
      ? { budgetPolicy: normalizeBudgetPolicy(record.budgetPolicy) }
      : {})
  };
}

function normalizeAgentIo(value: unknown): Record<string, TeamStateSchemaAgentIo> {
  const record = asRecord(value, "TeamConfiguration.stateSchema.agentIo");

  return Object.fromEntries(
    Object.entries(record).map(([agentId, entry]) => {
      const ioRecord = asRecord(entry, `TeamConfiguration.stateSchema.agentIo.${agentId}`);
      return [
        agentId,
        {
          ...(ioRecord.reads ? { reads: normalizeStringArray(ioRecord.reads, `${agentId}.reads`) } : {}),
          ...(ioRecord.writes ? { writes: normalizeStringArray(ioRecord.writes, `${agentId}.writes`) } : {})
        }
      ];
    })
  );
}

function normalizeSubWorkflows(value: unknown): Record<string, TeamConfiguration> {
  const record = asRecord(value, "TeamConfiguration.subWorkflows");

  return Object.fromEntries(
    Object.entries(record).map(([name, configuration]) => [
      name,
      configuration instanceof TeamConfiguration
        ? TeamConfiguration.parse(configuration.toJSON())
        : new TeamConfiguration(configuration)
    ])
  );
}

function validateNormalizedTeamConfiguration(data: TeamConfigurationData): void {
  const agentIds = new Set<string>();

  for (const agent of data.agents) {
    if (agentIds.has(agent.id)) {
      throw new Error(`Team '${data.teamName}' contains duplicate agent id '${agent.id}'.`);
    }

    agentIds.add(agent.id);
  }

  for (const step of data.workflow.steps) {
    if (step.type !== "sub_workflow" && !agentIds.has(step.agent)) {
      throw new Error(
        `Team '${data.teamName}' workflow step '${step.agent}' references unknown agent '${step.agent}'.`
      );
    }

    if (step.type === "sub_workflow" && !step.team) {
      throw new Error(
        `Team '${data.teamName}' sub_workflow step '${step.agent}' must define 'team'.`
      );
    }
  }

  const agentIo = data.stateSchema?.agentIo;
  if (agentIo) {
    for (const agentId of Object.keys(agentIo)) {
      if (!agentIds.has(agentId)) {
        throw new Error(
          `Team '${data.teamName}' stateSchema.agentIo references unknown agent '${agentId}'.`
        );
      }
    }
  }
}

function normalizeWorkflowStepType(value: string): WorkflowStepType {
  const allowed = new Set<WorkflowStepType>([
    "sequential",
    "parallel_fan_out",
    "conditional",
    "human_gate",
    "gated",
    "sub_workflow"
  ]);

  if (!allowed.has(value as WorkflowStepType)) {
    throw new Error(`Unsupported workflow step type '${value}'.`);
  }

  return value as WorkflowStepType;
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

function normalizeBudgetPolicy(value: string): CollaborationBudgetPolicy {
  const allowed = new Set<CollaborationBudgetPolicy>([
    "inherit_parent",
    "fixed",
    "unlimited"
  ]);

  if (!allowed.has(value as CollaborationBudgetPolicy)) {
    throw new Error(`Unsupported collaboration budget policy '${value}'.`);
  }

  return value as CollaborationBudgetPolicy;
}

function normalizeParallelItemSource(value: string): ParallelItemSource {
  const allowed = new Set<ParallelItemSource>([
    "parallelItems",
    "parallel_items",
    "taskData",
    "task_data"
  ]);

  if (!allowed.has(value as ParallelItemSource)) {
    throw new Error(`Unsupported parallel item source '${value}'.`);
  }

  return value as ParallelItemSource;
}

function normalizeStringRecord(value: unknown): Record<string, string> {
  const record = asRecord(value, "string record");
  return Object.fromEntries(
    Object.entries(record).map(([key, entryValue]) => {
      if (typeof entryValue !== "string") {
        throw new Error(`Expected string record value for '${key}'.`);
      }

      return [key, entryValue];
    })
  );
}

function normalizeStringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${path} must be an array of strings.`);
  }

  return value.map((entry, index) => readRequiredString(entry, `${path}[${index}]`));
}

function normalizeNullableString(value: unknown): string | null {
  if (value === null) {
    return null;
  }

  return readRequiredString(value, "nullable string");
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

function cloneTeamValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}