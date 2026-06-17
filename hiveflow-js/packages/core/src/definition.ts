import { Agent } from "./agent.js";
import type { ActionPolicy, AgentBehavior } from "./agent.js";
import { CollaborationRuntime } from "./collaboration.js";
import type { CollaborationConfig } from "./collaboration.js";
import type { ModelAdapter, ToolDefinition } from "./model.js";
import type { WorkflowData } from "./types.js";
import { WorkflowEngine } from "./workflow.js";
import type { WorkflowStep } from "./workflow.js";
import type { ArchetypeLibrary } from "./archetype.js";
import { safeClone } from "./internal.js";

export interface ModelDefinition {
  kind: string;
  options?: WorkflowData;
}

export interface AgentDefinition {
  id: string;
  role: string;
  instructions: string;
  model: ModelDefinition;
  behavior?: AgentBehavior;
  prompt?: string;
  toolIds?: string[];
  actionPolicy?: ActionPolicy;
  rollbackOnFailure?: boolean;
  rollbackAction?: string;
  temperature?: number;
  maxOutputTokens?: number;
}

export interface WorkflowDefinition {
  id?: string;
  steps: WorkflowStep[];
  agents: AgentDefinition[];
  collaboration?: CollaborationConfig;
  subWorkflows?: Record<string, WorkflowDefinition>;
}

export interface WorkflowRuntime {
  workflow: WorkflowEngine;
  agents: Record<string, Agent>;
  definition: WorkflowDefinition;
}

export type ModelFactory = (definition: ModelDefinition) => ModelAdapter;

export interface WorkflowRuntimeCatalogOptions {
  tools?: Record<string, ToolDefinition>;
  modelFactories?: Record<string, ModelFactory>;
  archetypeLibrary?: ArchetypeLibrary;
}

export class WorkflowRuntimeCatalog {
  private readonly tools = new Map<string, ToolDefinition>();
  private readonly modelFactories = new Map<string, ModelFactory>();
  private readonly archetypeLibrary: ArchetypeLibrary | undefined;

  constructor(options: WorkflowRuntimeCatalogOptions = {}) {
    this.archetypeLibrary = options.archetypeLibrary;

    for (const [toolId, tool] of Object.entries(options.tools ?? {})) {
      this.registerTool(toolId, tool);
    }

    for (const [kind, factory] of Object.entries(options.modelFactories ?? {})) {
      this.registerModelFactory(kind, factory);
    }
  }

  registerTool(toolId: string, tool: ToolDefinition): this {
    this.tools.set(toolId, tool);
    return this;
  }

  registerModelFactory(kind: string, factory: ModelFactory): this {
    this.modelFactories.set(kind, factory);
    return this;
  }

  build(definition: WorkflowDefinition): WorkflowRuntime {
    let collaborationRuntime: CollaborationRuntime | undefined;
    if (definition.collaboration) {
      const collaborationOptions = {
        config: definition.collaboration,
        tools: Object.fromEntries(this.tools.entries()),
        createModel: (modelDefinition: ModelDefinition) => this.createModel(modelDefinition)
      } as {
        config: CollaborationConfig;
        tools: Record<string, ToolDefinition>;
        createModel: (modelDefinition: ModelDefinition) => ModelAdapter;
        archetypeLibrary?: ArchetypeLibrary;
      };

      if (this.archetypeLibrary) {
        collaborationOptions.archetypeLibrary = this.archetypeLibrary;
      }

      collaborationRuntime = new CollaborationRuntime(collaborationOptions);
    }
    const agents: Record<string, Agent> = {};

    for (const agentDefinition of definition.agents) {
      if (agents[agentDefinition.id]) {
        throw new Error(`Workflow definition contains duplicate agent '${agentDefinition.id}'.`);
      }

      agents[agentDefinition.id] = this.buildAgent(agentDefinition, collaborationRuntime);
    }

    collaborationRuntime?.registerInitialAgents(agents);

    const subWorkflowEntries = Object.entries(definition.subWorkflows ?? {}).map(
      ([name, subWorkflowDefinition]) => {
        const runtime = this.build(subWorkflowDefinition);

        return [name, { workflow: runtime.workflow, agents: runtime.agents }] as const;
      }
    );

    const workflowOptions = {
      steps: definition.steps
    } as {
      steps: WorkflowStep[];
      subWorkflows?: Record<string, { workflow: WorkflowEngine; agents: Record<string, Agent> }>;
    };

    if (subWorkflowEntries.length > 0) {
      workflowOptions.subWorkflows = Object.fromEntries(subWorkflowEntries);
    }

    const workflow = new WorkflowEngine(workflowOptions);
    if (collaborationRuntime) {
      collaborationRuntime.setEventSink((event) => workflow.emitRuntimeEvent(event));
    }

    return {
      workflow,
      agents,
      definition: cloneWorkflowDefinition(definition)
    };
  }

  private buildAgent(
    definition: AgentDefinition,
    collaborationRuntime?: CollaborationRuntime
  ): Agent {
    const agentOptions = {
      id: definition.id,
      role: definition.role,
      instructions: definition.instructions,
      model: this.createModel(definition.model)
    } as {
      id: string;
      role: string;
      instructions: string;
      model: ModelAdapter;
      behavior?: AgentBehavior;
      prompt?: string;
      tools?: Record<string, ToolDefinition>;
      actionPolicy?: ActionPolicy;
      rollbackOnFailure?: boolean;
      rollbackAction?: string;
      temperature?: number;
      maxOutputTokens?: number;
      collaboration?: CollaborationRuntime;
    };

    if (definition.behavior) {
      agentOptions.behavior = definition.behavior;
    }

    if (definition.prompt) {
      agentOptions.prompt = definition.prompt;
    }

    if (definition.toolIds && definition.toolIds.length > 0) {
      agentOptions.tools = Object.fromEntries(
        definition.toolIds.map((toolId) => [toolId, this.resolveTool(toolId)])
      );
    }

    if (definition.actionPolicy) {
      agentOptions.actionPolicy = definition.actionPolicy;
    }

    if (definition.rollbackOnFailure === true) {
      agentOptions.rollbackOnFailure = true;
    }

    if (definition.rollbackAction) {
      agentOptions.rollbackAction = definition.rollbackAction;
    }

    if (typeof definition.temperature === "number") {
      agentOptions.temperature = definition.temperature;
    }

    if (typeof definition.maxOutputTokens === "number") {
      agentOptions.maxOutputTokens = definition.maxOutputTokens;
    }

    if (collaborationRuntime && definition.behavior === "orchestrator") {
      agentOptions.collaboration = collaborationRuntime;
    }

    return new Agent(agentOptions);
  }

  private createModel(definition: ModelDefinition): ModelAdapter {
    const factory = this.modelFactories.get(definition.kind);
    if (!factory) {
      throw new Error(`Workflow runtime catalog has no model factory for kind '${definition.kind}'.`);
    }

    return factory(definition);
  }

  private resolveTool(toolId: string): ToolDefinition {
    const tool = this.tools.get(toolId);
    if (!tool) {
      throw new Error(`Workflow runtime catalog has no tool registered for '${toolId}'.`);
    }

    return tool;
  }
}

function cloneWorkflowDefinition(definition: WorkflowDefinition): WorkflowDefinition {
  return safeClone(definition);
}