import { z } from "zod";

import { Agent } from "./agent.js";
import type { ActionPolicy, AgentBehavior, AgentCollaborationContext } from "./agent.js";
import type { ModelDefinition } from "./definition.js";
import type { ModelAdapter, ToolDefinition, ToolExecutionContext } from "./model.js";
import type { WorkflowData } from "./types.js";
import type { ArchetypeDefinition, ArchetypeLibrary } from "./archetype.js";

const DEFAULT_MAX_DELEGATION_DEPTH = 3;
const DEFAULT_MAX_SPAWNED_AGENTS = 10;
const DEFAULT_DELEGATION_TIMEOUT_SECONDS = 300;
const SUPPORTED_BEHAVIORS = new Set<AgentBehavior>([
  "llm_only",
  "tool_user",
  "orchestrator",
  "human_gate",
  "action_executor"
]);

export type CollaborationBudgetPolicy = "inherit_parent" | "fixed" | "unlimited";

export interface CollaborationConfig {
  enabled?: boolean;
  maxDelegationDepth?: number;
  maxSpawnedAgents?: number;
  allowRecursiveOrchestrators?: boolean;
  delegationTimeoutSeconds?: number;
  budgetPolicy?: CollaborationBudgetPolicy;
}

export interface DelegateTaskInput {
  task: string;
  delegate_to?: string;
  context?: WorkflowData;
  expected_output?: string;
}

export interface SpawnAgentCustomDefinition {
  role: string;
  systemPrompt: string;
  behavior?: AgentBehavior;
  toolIds?: string[];
  prompt?: string;
  temperature?: number;
  maxOutputTokens?: number;
}

export interface SpawnAgentInput {
  archetype?: string;
  custom_definition?: SpawnAgentCustomDefinition;
  agent_id?: string;
}

export type CollaborationRuntimeEvent =
  | {
      type: "agent_spawned";
      stepId: string;
      agentId: string;
      state: WorkflowData;
      spawnedBy: string;
      archetype?: string;
    }
  | {
      type: "delegation_started";
      stepId: string;
      agentId: string;
      state: WorkflowData;
      delegatedBy: string;
      delegateTo: string;
      task: string;
      depth: number;
    }
  | {
      type: "delegation_completed";
      stepId: string;
      agentId: string;
      state: WorkflowData;
      delegatedBy: string;
      delegateTo: string;
      task: string;
      depth: number;
      resultSummary: string;
    }
  | {
      type: "delegation_failed";
      stepId: string;
      agentId: string;
      state: WorkflowData;
      delegatedBy: string;
      delegateTo: string;
      task: string;
      depth: number;
      error: string;
    };

interface CollaborationRuntimeOptions {
  config?: CollaborationConfig;
  archetypeLibrary?: ArchetypeLibrary;
  tools?: Record<string, ToolDefinition>;
  createModel?: (definition: ModelDefinition) => ModelAdapter;
}

type CollaborationEventSink = (event: CollaborationRuntimeEvent) => Promise<void> | void;

const spawnAgentSchema = z.object({
  archetype: z.string().optional(),
  custom_definition: z
    .object({
      role: z.string().optional(),
      system_prompt: z.string().optional(),
      systemPrompt: z.string().optional(),
      behavior_type: z.string().optional(),
      behaviorType: z.string().optional(),
      tools: z.array(z.string()).optional(),
      prompt: z.string().optional(),
      temperature: z.number().optional(),
      max_output_tokens: z.number().optional(),
      maxOutputTokens: z.number().optional()
    })
    .passthrough()
    .optional(),
  agent_id: z.string().optional()
});

export class CollaborationRuntime implements AgentCollaborationContext {
  private readonly agents = new Map<string, Agent>();
  private readonly tools = new Map<string, ToolDefinition>();
  private readonly config: Required<CollaborationConfig>;
  private readonly archetypeLibrary: ArchetypeLibrary | undefined;
  private readonly createModel: ((definition: ModelDefinition) => ModelAdapter) | undefined;
  private eventSink: CollaborationEventSink | undefined;
  private spawnedAgents = 0;

  constructor(options: CollaborationRuntimeOptions = {}) {
    this.config = normalizeCollaborationConfig(options.config);
    this.archetypeLibrary = options.archetypeLibrary;
    this.createModel = options.createModel;

    for (const [toolId, tool] of Object.entries(options.tools ?? {})) {
      this.tools.set(toolId, tool);
    }
  }

  registerInitialAgents(agents: Record<string, Agent>): this {
    for (const [agentId, agent] of Object.entries(agents)) {
      this.agents.set(agentId, agent);
    }

    return this;
  }

  setEventSink(eventSink: CollaborationEventSink): this {
    this.eventSink = eventSink;
    return this;
  }

  listAgentIds(): string[] {
    return Array.from(this.agents.keys()).sort();
  }

  listArchetypes(): string[] {
    return this.archetypeLibrary?.listArchetypes() ?? [];
  }

  createOrchestratorTools(agent: Agent): Record<string, ToolDefinition> {
    if (this.config.enabled !== true) {
      return {};
    }

    return {
      delegate_task: {
        description:
          "Delegate a sub-task to another agent or dynamically selected specialist and return the result.",
        inputSchema: z.object({
          task: z.string().min(1),
          delegate_to: z.string().optional(),
          context: z.record(z.string(), z.unknown()).optional(),
          expected_output: z.string().optional()
        }),
        execute: async (input, context) =>
          this.delegateTask(agent, input as DelegateTaskInput, context)
      },
      spawn_agent: {
        description:
          "Create a new specialist agent from an archetype or inline definition and return its agent id.",
        inputSchema: spawnAgentSchema,
        execute: async (input, context) =>
          this.spawnAgent(agent, input as Record<string, unknown>, context)
      }
    };
  }

  private async delegateTask(
    orchestrator: Agent,
    input: DelegateTaskInput,
    context: ToolExecutionContext
  ): Promise<WorkflowData> {
    const currentDepth = readDelegationDepth(context.state);
    if (currentDepth >= this.config.maxDelegationDepth) {
      throw new Error(
        `Delegation depth limit reached (${this.config.maxDelegationDepth}) for orchestrator '${orchestrator.id}'.`
      );
    }

    const target = this.resolveDelegateTarget(orchestrator, input.task, input.delegate_to);
    if (target.id === orchestrator.id) {
      throw new Error(`Orchestrator '${orchestrator.id}' cannot delegate to itself.`);
    }

    const stepId = context.stepId ?? orchestrator.id;
    const depth = currentDepth + 1;
    await this.emit({
      type: "delegation_started",
      stepId,
      agentId: orchestrator.id,
      state: cloneWorkflowData(context.state),
      delegatedBy: orchestrator.id,
      delegateTo: target.id,
      task: input.task,
      depth
    });

    const delegatedState = buildDelegatedState(
      context.state,
      orchestrator.id,
      target.id,
      input.task,
      input.context,
      depth
    );

    try {
      const execution = await withTimeout(
        target.execute(delegatedState, { stepId }),
        this.config.delegationTimeoutSeconds,
        `Delegation from '${orchestrator.id}' to '${target.id}' timed out after ${this.config.delegationTimeoutSeconds} seconds.`
      );

      await this.emit({
        type: "delegation_completed",
        stepId,
        agentId: orchestrator.id,
        state: cloneWorkflowData(context.state),
        delegatedBy: orchestrator.id,
        delegateTo: target.id,
        task: input.task,
        depth,
        resultSummary: summarizeValue(execution.output)
      });

      return {
        agentId: target.id,
        output: execution.output,
        statePatch: execution.statePatch,
        prompt: execution.prompt,
        ...(input.expected_output ? { expectedOutput: input.expected_output } : {})
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await this.emit({
        type: "delegation_failed",
        stepId,
        agentId: orchestrator.id,
        state: cloneWorkflowData(context.state),
        delegatedBy: orchestrator.id,
        delegateTo: target.id,
        task: input.task,
        depth,
        error: message
      });
      throw error;
    }
  }

  private async spawnAgent(
    orchestrator: Agent,
    rawInput: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<WorkflowData> {
    const input = normalizeSpawnAgentInput(rawInput);

    if (this.spawnedAgents >= this.config.maxSpawnedAgents) {
      throw new Error(
        `Spawn limit reached (${this.config.maxSpawnedAgents}) for the current workflow execution.`
      );
    }

    const definition = this.resolveSpawnDefinition(orchestrator, input);
    const requestedId = input.agent_id;
    const agentId = requestedId
      ? this.ensureAvailableAgentId(requestedId)
      : this.generateSpawnedAgentId(definition.idHint);
    const agent = new Agent({
      id: agentId,
      role: definition.role,
      instructions: definition.instructions,
      model: definition.model,
      behavior: definition.behavior,
      ...(definition.prompt ? { prompt: definition.prompt } : {}),
      ...(definition.tools ? { tools: definition.tools } : {}),
      ...(definition.actionPolicy ? { actionPolicy: definition.actionPolicy } : {}),
      ...(typeof definition.temperature === "number"
        ? { temperature: definition.temperature }
        : {}),
      ...(typeof definition.maxOutputTokens === "number"
        ? { maxOutputTokens: definition.maxOutputTokens }
        : {}),
      ...(definition.behavior === "orchestrator" ? { collaboration: this } : {})
    });

    this.agents.set(agentId, agent);
    this.spawnedAgents += 1;

    await this.emit({
      type: "agent_spawned",
      stepId: context.stepId ?? orchestrator.id,
      agentId,
      state: cloneWorkflowData(context.state),
      spawnedBy: orchestrator.id,
      ...(definition.archetype ? { archetype: definition.archetype } : {})
    });

    return {
      agentId,
      role: definition.role,
      behavior: definition.behavior,
      ...(definition.archetype ? { archetype: definition.archetype } : {})
    };
  }

  private resolveDelegateTarget(
    orchestrator: Agent,
    task: string,
    requestedTarget: string | undefined
  ): Agent {
    if (requestedTarget && requestedTarget !== "auto") {
      const directTarget = this.agents.get(requestedTarget);
      if (!directTarget) {
        throw new Error(`Delegate target '${requestedTarget}' was not found in the active agent pool.`);
      }

      return directTarget;
    }

    const candidates = this.listAgentIds()
      .filter((agentId) => agentId !== orchestrator.id)
      .map((agentId) => this.agents.get(agentId))
      .filter((agent): agent is Agent => agent instanceof Agent);

    if (candidates.length === 0) {
      return this.spawnDefaultDelegate(orchestrator, task);
    }

    const rankedCandidates = candidates
      .map((agent) => ({
        agent,
        score: scoreAgentForTask(agent, task)
      }))
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score;
        }

        if (left.agent.behavior !== right.agent.behavior) {
          return left.agent.behavior === "orchestrator" ? 1 : -1;
        }

        return left.agent.id.localeCompare(right.agent.id);
      });

    return rankedCandidates[0]?.agent ?? this.spawnDefaultDelegate(orchestrator, task);
  }

  private spawnDefaultDelegate(orchestrator: Agent, task: string): Agent {
    const agentId = this.generateSpawnedAgentId("delegate");
    const agent = new Agent({
      id: agentId,
      role: "Delegated Specialist",
      instructions: `Complete the delegated task accurately and concisely. Task focus: ${task}`,
      model: orchestrator.model,
      behavior: "llm_only"
    });

    this.agents.set(agentId, agent);
    this.spawnedAgents += 1;
    return agent;
  }

  private resolveSpawnDefinition(
    orchestrator: Agent,
    input: SpawnAgentInput
  ): {
    idHint: string;
    role: string;
    instructions: string;
    model: ModelAdapter;
    behavior: AgentBehavior;
    prompt?: string;
    tools?: Record<string, ToolDefinition>;
    actionPolicy?: ActionPolicy;
    temperature?: number;
    maxOutputTokens?: number;
    archetype?: string;
  } {
    if (input.archetype) {
      const archetype = this.archetypeLibrary?.get(input.archetype);
      if (!archetype) {
        throw new Error(`Archetype '${input.archetype}' was not found in the available ArchetypeLibrary.`);
      }

      return this.buildSpawnDefinitionFromArchetype(orchestrator, input.archetype, archetype);
    }

    if (!input.custom_definition) {
      throw new Error("spawn_agent requires either 'archetype' or 'custom_definition'.");
    }

    return this.buildSpawnDefinitionFromCustom(orchestrator, input.custom_definition);
  }

  private buildSpawnDefinitionFromArchetype(
    orchestrator: Agent,
    archetypeName: string,
    archetype: ArchetypeDefinition
  ): {
    idHint: string;
    role: string;
    instructions: string;
    model: ModelAdapter;
    behavior: AgentBehavior;
    prompt?: string;
    tools?: Record<string, ToolDefinition>;
    actionPolicy?: ActionPolicy;
    temperature?: number;
    maxOutputTokens?: number;
    archetype?: string;
  } {
    const behavior = archetype.behavior ?? "llm_only";
    this.assertRecursiveBehaviorAllowed(behavior);

    return {
      idHint: archetype.id,
      role: archetype.role,
      instructions: archetype.instructions,
      model:
        archetype.model && typeof archetype.model === "object"
          ? this.createSpawnedModel(archetype.model)
          : orchestrator.model,
      behavior,
      ...(archetype.prompt ? { prompt: archetype.prompt } : {}),
      ...(archetype.toolIds ? { tools: this.resolveToolsById(archetype.toolIds) } : {}),
      ...(archetype.actionPolicy ? { actionPolicy: archetype.actionPolicy } : {}),
      ...(typeof archetype.temperature === "number" ? { temperature: archetype.temperature } : {}),
      ...(typeof archetype.maxOutputTokens === "number"
        ? { maxOutputTokens: archetype.maxOutputTokens }
        : {}),
      archetype: archetypeName
    };
  }

  private buildSpawnDefinitionFromCustom(
    orchestrator: Agent,
    definition: SpawnAgentCustomDefinition
  ): {
    idHint: string;
    role: string;
    instructions: string;
    model: ModelAdapter;
    behavior: AgentBehavior;
    prompt?: string;
    tools?: Record<string, ToolDefinition>;
    temperature?: number;
    maxOutputTokens?: number;
  } {
    const behavior = definition.behavior ?? "llm_only";
    this.assertRecursiveBehaviorAllowed(behavior);

    return {
      idHint: slugify(definition.role),
      role: definition.role,
      instructions: definition.systemPrompt,
      model: orchestrator.model,
      behavior,
      ...(definition.prompt ? { prompt: definition.prompt } : {}),
      ...(definition.toolIds ? { tools: this.resolveToolsById(definition.toolIds) } : {}),
      ...(typeof definition.temperature === "number" ? { temperature: definition.temperature } : {}),
      ...(typeof definition.maxOutputTokens === "number"
        ? { maxOutputTokens: definition.maxOutputTokens }
        : {})
    };
  }

  private createSpawnedModel(definition: ModelDefinition): ModelAdapter {
    if (!this.createModel) {
      throw new Error(
        "Collaboration runtime cannot create spawned agent models because no model factory is available."
      );
    }

    return this.createModel(definition);
  }

  private resolveToolsById(toolIds: string[]): Record<string, ToolDefinition> {
    return Object.fromEntries(toolIds.map((toolId) => [toolId, this.resolveTool(toolId)]));
  }

  private resolveTool(toolId: string): ToolDefinition {
    const tool = this.tools.get(toolId);
    if (!tool) {
      throw new Error(`Collaboration runtime has no tool registered for '${toolId}'.`);
    }

    return tool;
  }

  private ensureAvailableAgentId(agentId: string): string {
    if (this.agents.has(agentId)) {
      throw new Error(`Agent id '${agentId}' is already in use by the active collaboration runtime.`);
    }

    return agentId;
  }

  private generateSpawnedAgentId(hint: string): string {
    let suffix = this.spawnedAgents + 1;
    const base = slugify(hint) || "agent";

    while (this.agents.has(`spawned_${base}_${suffix}`)) {
      suffix += 1;
    }

    return `spawned_${base}_${suffix}`;
  }

  private assertRecursiveBehaviorAllowed(behavior: AgentBehavior): void {
    if (behavior === "orchestrator" && this.config.allowRecursiveOrchestrators !== true) {
      throw new Error(
        "Spawned agents cannot be orchestrators unless allowRecursiveOrchestrators is enabled."
      );
    }
  }

  private async emit(event: CollaborationRuntimeEvent): Promise<void> {
    if (!this.eventSink) {
      return;
    }

    await this.eventSink(event);
  }
}

function normalizeCollaborationConfig(
  config: CollaborationConfig | undefined
): Required<CollaborationConfig> {
  const maxDelegationDepth =
    typeof config?.maxDelegationDepth === "number" && config.maxDelegationDepth > 0
      ? Math.floor(config.maxDelegationDepth)
      : DEFAULT_MAX_DELEGATION_DEPTH;
  const maxSpawnedAgents =
    typeof config?.maxSpawnedAgents === "number" && config.maxSpawnedAgents > 0
      ? Math.floor(config.maxSpawnedAgents)
      : DEFAULT_MAX_SPAWNED_AGENTS;
  const delegationTimeoutSeconds =
    typeof config?.delegationTimeoutSeconds === "number" && config.delegationTimeoutSeconds > 0
      ? Math.floor(config.delegationTimeoutSeconds)
      : DEFAULT_DELEGATION_TIMEOUT_SECONDS;

  return {
    enabled: config?.enabled !== false,
    maxDelegationDepth,
    maxSpawnedAgents,
    allowRecursiveOrchestrators: config?.allowRecursiveOrchestrators === true,
    delegationTimeoutSeconds,
    budgetPolicy: normalizeBudgetPolicy(config?.budgetPolicy)
  };
}

function normalizeBudgetPolicy(
  value: CollaborationBudgetPolicy | undefined
): CollaborationBudgetPolicy {
  if (value === "fixed" || value === "unlimited") {
    return value;
  }

  return "inherit_parent";
}

function normalizeSpawnAgentInput(value: Record<string, unknown>): SpawnAgentInput {
  const parsed = spawnAgentSchema.parse(value);
  const customDefinition = parsed.custom_definition
    ? normalizeSpawnAgentCustomDefinition(parsed.custom_definition as Record<string, unknown>)
    : undefined;

  if (!parsed.archetype && !customDefinition) {
    throw new Error("spawn_agent requires either 'archetype' or 'custom_definition'.");
  }

  return {
    ...(parsed.archetype ? { archetype: parsed.archetype } : {}),
    ...(customDefinition ? { custom_definition: customDefinition } : {}),
    ...(parsed.agent_id ? { agent_id: parsed.agent_id } : {})
  };
}

function normalizeSpawnAgentCustomDefinition(
  value: Record<string, unknown>
): SpawnAgentCustomDefinition {
  const role = typeof value.role === "string" && value.role.trim().length > 0
    ? value.role.trim()
    : undefined;
  const systemPromptValue = value.system_prompt ?? value.systemPrompt;
  const systemPrompt =
    typeof systemPromptValue === "string" && systemPromptValue.trim().length > 0
      ? systemPromptValue.trim()
      : undefined;

  if (!role || !systemPrompt) {
    throw new Error(
      "spawn_agent custom_definition requires non-empty 'role' and 'system_prompt'."
    );
  }

  const behaviorValue = value.behavior_type ?? value.behaviorType;
  const behavior =
    typeof behaviorValue === "string" ? normalizeBehavior(behaviorValue) : "llm_only";
  const toolsValue = value.tools;
  const maxOutputTokensValue = value.max_output_tokens ?? value.maxOutputTokens;

  return {
    role,
    systemPrompt,
    behavior,
    ...(Array.isArray(toolsValue) ? { toolIds: toolsValue.map(String) } : {}),
    ...(typeof value.prompt === "string" ? { prompt: value.prompt } : {}),
    ...(typeof value.temperature === "number" ? { temperature: value.temperature } : {}),
    ...(typeof maxOutputTokensValue === "number"
      ? { maxOutputTokens: maxOutputTokensValue }
      : {})
  };
}

function normalizeBehavior(value: string): AgentBehavior {
  if (!SUPPORTED_BEHAVIORS.has(value as AgentBehavior)) {
    throw new Error(`Unsupported collaboration behavior '${value}'.`);
  }

  return value as AgentBehavior;
}

function buildDelegatedState(
  parentState: WorkflowData,
  orchestratorId: string,
  targetAgentId: string,
  task: string,
  context: WorkflowData | undefined,
  depth: number
): WorkflowData {
  const delegatedState: WorkflowData = {};

  for (const [key, value] of Object.entries(parentState)) {
    if (key.startsWith("_")) {
      continue;
    }

    if (isRawOutputKey(key) && !belongsToAgent(key, orchestratorId) && !belongsToAgent(key, targetAgentId)) {
      continue;
    }

    delegatedState[key] = cloneWorkflowData(value);
  }

  delegatedState.task = task;
  delegatedState.delegatedBy = orchestratorId;
  delegatedState.delegateTo = targetAgentId;
  delegatedState._delegation_depth = depth;

  if (context) {
    for (const [key, value] of Object.entries(context)) {
      delegatedState[key] = cloneWorkflowData(value);
    }
  }

  return delegatedState;
}

function readDelegationDepth(state: WorkflowData): number {
  const depth = state._delegation_depth;
  return typeof depth === "number" && Number.isFinite(depth) ? depth : 0;
}

function isRawOutputKey(key: string): boolean {
  return key.endsWith("Output") || key.endsWith("_output") || key.endsWith("Outputs");
}

function belongsToAgent(key: string, agentId: string): boolean {
  return key.startsWith(agentId);
}

function scoreAgentForTask(agent: Agent, task: string): number {
  const haystack = `${agent.id} ${agent.role} ${agent.instructions}`.toLowerCase();
  const tokens = task
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .map((token) => token.trim())
    .filter((token) => token.length >= 3);

  return tokens.reduce((score, token) => score + (haystack.includes(token) ? 1 : 0), 0);
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function summarizeValue(value: unknown): string {
  if (typeof value === "string") {
    return value.length > 160 ? `${value.slice(0, 157)}...` : value;
  }

  const serialized = serializeToolResult(value);
  return serialized.length > 160 ? `${serialized.slice(0, 157)}...` : serialized;
}

function serializeToolResult(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

async function withTimeout<T>(
  promise: Promise<T>,
  seconds: number,
  errorMessage: string
): Promise<T> {
  if (seconds <= 0) {
    return promise;
  }

  let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
  const timeoutPromise = new Promise<never>((_resolve, reject) => {
    timeoutHandle = setTimeout(() => reject(new Error(errorMessage)), seconds * 1000);
  });

  try {
    return await Promise.race([promise, timeoutPromise]);
  } finally {
    if (timeoutHandle) {
      clearTimeout(timeoutHandle);
    }
  }
}

function cloneWorkflowData<T>(value: T): T {
  if (value === undefined) {
    return value;
  }

  return JSON.parse(JSON.stringify(value)) as T;
}