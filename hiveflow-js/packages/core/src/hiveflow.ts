import type { CheckpointStorage, WorkflowCheckpoint } from "./checkpoint.js";
import { ArchetypeLibrary, TeamGenerator } from "./archetype.js";
import type {
  GenerateTeamFromLLMOptions,
  GenerateTeamOptions,
  TeamGenerationResult
} from "./archetype.js";
import { WorkflowRuntimeCatalog } from "./definition.js";
import type { WorkflowDefinition } from "./definition.js";
import { WorkflowEngine } from "./workflow.js";
import { WorkflowSession } from "./session.js";
import type { Agent } from "./agent.js";
import { TeamConfiguration, TeamLibrary } from "./team.js";
import type { ModelReferenceResolver, TeamDefinitionBuildOptions } from "./team.js";
import type { WorkflowData } from "./types.js";
import type { WorkflowResult } from "./workflow.js";
import type { LoadWorkflowSessionOptions, WorkflowSessionOptions } from "./session.js";

export interface HiveFlowOptions {
  checkpointStorage?: CheckpointStorage;
  runtimeCatalog?: WorkflowRuntimeCatalog;
  teamLibrary?: TeamLibrary;
  archetypeLibrary?: ArchetypeLibrary;
}

export interface HiveFlowComposeTeamOptions extends GenerateTeamOptions {
  archetypeLibrary?: ArchetypeLibrary;
}

export interface HiveFlowComposeTeamFromLLMOptions extends GenerateTeamFromLLMOptions {}

export interface HiveFlowDefinitionSessionOptions {
  definition: WorkflowDefinition;
  initialState?: WorkflowData;
  checkpointStorage?: CheckpointStorage;
  sessionId?: string;
}

export interface HiveFlowTeamBuildOptions extends TeamDefinitionBuildOptions {
  team: string | TeamConfiguration;
}

export interface HiveFlowTeamSessionOptions extends HiveFlowTeamBuildOptions {
  initialState?: WorkflowData;
  checkpointStorage?: CheckpointStorage;
  sessionId?: string;
}

export interface HiveFlowRunOptions {
  workflow: WorkflowEngine;
  agents: Record<string, Agent>;
  initialState?: WorkflowData;
  checkpointStorage?: CheckpointStorage;
  sessionId?: string;
}

export interface HiveFlowResumeOptions {
  workflow: WorkflowEngine;
  agents: Record<string, Agent>;
  pausedResult: WorkflowResult;
  responses?: WorkflowData;
  checkpointStorage?: CheckpointStorage;
  sessionId?: string;
}

export interface HiveFlowLoadSessionOptions {
  workflow?: WorkflowEngine;
  agents?: Record<string, Agent>;
  sessionId: string;
  checkpointId?: string;
  checkpointStorage?: CheckpointStorage;
}

export interface HiveFlowResumeSessionOptions extends HiveFlowLoadSessionOptions {
  responses: WorkflowData;
}

export class HiveFlow {
  private readonly checkpointStorage: CheckpointStorage | undefined;
  private readonly runtimeCatalog: WorkflowRuntimeCatalog | undefined;
  private readonly teamLibraryInstance: TeamLibrary;
  private readonly archetypeLibraryInstance: ArchetypeLibrary;
  private readonly activeSessions = new Map<string, WorkflowSession>();

  constructor(options: HiveFlowOptions = {}) {
    this.checkpointStorage = options.checkpointStorage;
    this.runtimeCatalog = options.runtimeCatalog;
    this.teamLibraryInstance = options.teamLibrary ?? new TeamLibrary();
    this.archetypeLibraryInstance = options.archetypeLibrary ?? ArchetypeLibrary.fromBuiltIns();
  }

  teamLibrary(): TeamLibrary {
    return this.teamLibraryInstance;
  }

  archetypeLibrary(): ArchetypeLibrary {
    return this.archetypeLibraryInstance;
  }

  composeTeam(options: HiveFlowComposeTeamOptions): TeamConfiguration {
    const generator = new TeamGenerator({
      archetypeLibrary: options.archetypeLibrary ?? this.archetypeLibraryInstance
    });

    return generator.generateTeam(options);
  }

  async composeTeamFromLLM(
    options: HiveFlowComposeTeamFromLLMOptions
  ): Promise<TeamGenerationResult> {
    const generator = new TeamGenerator({
      archetypeLibrary: options.archetypeLibrary ?? this.archetypeLibraryInstance
    });

    return generator.generateTeamFromLLM(options);
  }

  createSession(options: WorkflowSessionOptions): WorkflowSession {
    const sessionOptions = {
      workflow: options.workflow,
      agents: options.agents
    } as WorkflowSessionOptions;

    if (options.initialState) {
      sessionOptions.initialState = options.initialState;
    }

    if (options.sessionId) {
      sessionOptions.sessionId = options.sessionId;
    }

    const checkpointStorage = options.checkpointStorage ?? this.checkpointStorage;
    if (checkpointStorage) {
      sessionOptions.checkpointStorage = checkpointStorage;
    }

    if (options.workflowDefinition) {
      sessionOptions.workflowDefinition = options.workflowDefinition;
    }

    const session = new WorkflowSession(sessionOptions);

    this.activeSessions.set(session.sessionId, session);
    return session;
  }

  createSessionFromDefinition(options: HiveFlowDefinitionSessionOptions): WorkflowSession {
    const runtime = this.resolveRuntimeCatalog().build(options.definition);

    const sessionOptions = {
      workflow: runtime.workflow,
      agents: runtime.agents,
      workflowDefinition: runtime.definition
    } as WorkflowSessionOptions;

    if (options.initialState) {
      sessionOptions.initialState = options.initialState;
    }

    if (options.sessionId) {
      sessionOptions.sessionId = options.sessionId;
    }

    if (options.checkpointStorage) {
      sessionOptions.checkpointStorage = options.checkpointStorage;
    }

    return this.createSession(sessionOptions);
  }

  createSessionFromTeam(options: HiveFlowTeamSessionOptions): WorkflowSession {
    const buildOptions = {} as TeamDefinitionBuildOptions;
    const teamLibrary = options.teamLibrary ?? this.teamLibraryInstance;

    if (teamLibrary) {
      buildOptions.teamLibrary = teamLibrary;
    }

    if (options.modelResolver) {
      buildOptions.modelResolver = options.modelResolver;
    }

    if (options.availableTools) {
      buildOptions.availableTools = options.availableTools;
    }

    const definition = this.resolveTeamConfiguration(options).toWorkflowDefinition(buildOptions);

    return this.createSessionFromDefinition({
      definition,
      ...(options.initialState ? { initialState: options.initialState } : {}),
      ...(options.checkpointStorage ? { checkpointStorage: options.checkpointStorage } : {}),
      ...(options.sessionId ? { sessionId: options.sessionId } : {})
    });
  }

  async runSession(options: WorkflowSessionOptions): Promise<WorkflowSession> {
    const session = this.createSession(options);
    await session.run();
    this.pruneSession(session);
    return session;
  }

  async runSessionFromDefinition(
    options: HiveFlowDefinitionSessionOptions
  ): Promise<WorkflowSession> {
    const session = this.createSessionFromDefinition(options);
    await session.run();
    this.pruneSession(session);
    return session;
  }

  async runSessionFromTeam(options: HiveFlowTeamSessionOptions): Promise<WorkflowSession> {
    const session = this.createSessionFromTeam(options);
    await session.run();
    this.pruneSession(session);
    return session;
  }

  async loadSession(options: HiveFlowLoadSessionOptions): Promise<WorkflowSession> {
    const existingSession = this.activeSessions.get(options.sessionId);
    if (existingSession) {
      return existingSession;
    }

    const checkpointStorage = this.resolveCheckpointStorage(options.checkpointStorage);
    const checkpoint = await checkpointStorage.load(options.sessionId, options.checkpointId);
    if (!checkpoint) {
      throw new Error(`No checkpoint found for session '${options.sessionId}'.`);
    }

    const runtimeOptions = {
      checkpoint
    } as {
      workflow?: WorkflowEngine;
      agents?: Record<string, Agent>;
      checkpoint: WorkflowCheckpoint;
    };

    if (options.workflow) {
      runtimeOptions.workflow = options.workflow;
    }

    if (options.agents) {
      runtimeOptions.agents = options.agents;
    }

    const runtime = this.resolveSessionRuntime(runtimeOptions);
    const loadOptions: LoadWorkflowSessionOptions = {
      workflow: runtime.workflow,
      agents: runtime.agents,
      sessionId: options.sessionId,
      checkpointStorage,
      checkpoint
    };

    if (options.checkpointId) {
      loadOptions.checkpointId = options.checkpointId;
    }

    if (checkpoint.workflowDefinition) {
      loadOptions.workflowDefinition = checkpoint.workflowDefinition;
    }

    const session = await WorkflowSession.load(loadOptions);
    this.activeSessions.set(session.sessionId, session);
    return session;
  }

  async resumeSession(options: HiveFlowResumeSessionOptions): Promise<WorkflowSession> {
    const session = await this.loadSession(options);
    await session.resume(options.responses);
    this.pruneSession(session);
    return session;
  }

  async run(options: HiveFlowRunOptions): Promise<WorkflowResult> {
    const request = {
      agents: options.agents
    } as {
      agents: Record<string, Agent>;
      initialState?: WorkflowData;
      checkpointStorage?: CheckpointStorage;
      sessionId?: string;
    };

    if (options.initialState) {
      request.initialState = options.initialState;
    }

    const checkpointStorage = options.checkpointStorage ?? this.checkpointStorage;
    if (checkpointStorage) {
      request.checkpointStorage = checkpointStorage;
    }

    if (options.sessionId) {
      request.sessionId = options.sessionId;
    }

    return options.workflow.execute(request);
  }

  async runFromTeam(options: HiveFlowTeamSessionOptions): Promise<WorkflowResult> {
    const session = await this.runSessionFromTeam(options);
    if (!session.result) {
      throw new Error("HiveFlow.runFromTeam() did not produce a workflow result.");
    }

    return session.result;
  }

  async resume(options: HiveFlowResumeOptions): Promise<WorkflowResult> {
    const request = {
      agents: options.agents,
      pausedResult: options.pausedResult
    } as {
      agents: Record<string, Agent>;
      pausedResult: WorkflowResult;
      responses?: WorkflowData;
      checkpointStorage?: CheckpointStorage;
      sessionId?: string;
    };

    if (options.responses) {
      request.responses = options.responses;
    }

    const checkpointStorage = options.checkpointStorage ?? this.checkpointStorage;
    if (checkpointStorage) {
      request.checkpointStorage = checkpointStorage;
    }

    if (options.sessionId) {
      request.sessionId = options.sessionId;
    }

    return options.workflow.resume(request);
  }

  private resolveCheckpointStorage(storage?: CheckpointStorage): CheckpointStorage {
    if (storage) {
      return storage;
    }

    if (this.checkpointStorage) {
      return this.checkpointStorage;
    }

    throw new Error("HiveFlow requires checkpointStorage for session loading and durable resume.");
  }

  private resolveRuntimeCatalog(): WorkflowRuntimeCatalog {
    if (this.runtimeCatalog) {
      return this.runtimeCatalog;
    }

    throw new Error("HiveFlow requires runtimeCatalog to build workflows from definitions.");
  }

  private resolveTeamConfiguration(options: HiveFlowTeamBuildOptions): TeamConfiguration {
    if (options.team instanceof TeamConfiguration) {
      return TeamConfiguration.parse(options.team.toJSON());
    }

    const teamLibrary = options.teamLibrary ?? this.teamLibraryInstance;
    const configuration = teamLibrary.get(options.team);
    if (!configuration) {
      throw new Error(`Team '${options.team}' was not found in the available TeamLibrary.`);
    }

    return configuration;
  }

  private resolveSessionRuntime(options: {
    workflow?: WorkflowEngine;
    agents?: Record<string, Agent>;
    checkpoint: WorkflowCheckpoint;
  }): {
    workflow: WorkflowEngine;
    agents: Record<string, Agent>;
  } {
    const { workflow, agents, checkpoint } = options;

    if (workflow && agents) {
      return { workflow, agents };
    }

    if (workflow || agents) {
      throw new Error(
        "HiveFlow.loadSession requires both workflow and agents when runtime objects are supplied manually."
      );
    }

    if (!checkpoint.workflowDefinition) {
      throw new Error(
        `Checkpoint '${checkpoint.checkpointId}' for session '${checkpoint.sessionId}' does not contain a workflow definition. Supply workflow and agents manually or start the session with createSessionFromDefinition().`
      );
    }

    const runtime = this.resolveRuntimeCatalog().build(checkpoint.workflowDefinition);
    return {
      workflow: runtime.workflow,
      agents: runtime.agents
    };
  }

  private pruneSession(session: WorkflowSession): void {
    if (session.status === "completed" || session.status === "failed") {
      this.activeSessions.delete(session.sessionId);
    }
  }
}