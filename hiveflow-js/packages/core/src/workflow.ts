import { randomUUID } from "node:crypto";

import { createWorkflowCheckpoint } from "./checkpoint.js";
import type { CheckpointStorage } from "./checkpoint.js";
import type { WorkflowDefinition } from "./definition.js";
import { Agent } from "./agent.js";
import type { ActionPolicy, ActionProposal, ActionRecord, RollbackRecord } from "./agent.js";
import {
  normalizeActionErrorRollbackRecord,
  normalizeActionProposals,
  normalizeActionRecords
} from "./internal.js";
import { WorkflowState } from "./state.js";
import type { TokenUsage, WorkflowData } from "./types.js";

const DEFAULT_MAX_CONDITIONAL_ITERATIONS = 3;
const DEFAULT_MAX_SUB_WORKFLOW_DEPTH = 5;

type ParallelItemSource = "parallelItems" | "parallel_items" | "taskData" | "task_data";

type WorkflowStateMapping = Record<string, string>;

export type WorkflowStepType =
  | "sequential"
  | "parallel_fan_out"
  | "conditional"
  | "human_gate"
  | "gated"
  | "sub_workflow";

export type WorkflowStatus = "completed" | "failed" | "paused";

export type WorkflowPauseReason = "gated" | "human_gate" | "action_approval" | "action_error";

export interface WorkflowStep {
  id: string;
  agent: string;
  type: WorkflowStepType;
  team?: string;
  inputMapping?: WorkflowStateMapping;
  outputMapping?: WorkflowStateMapping;
  next?: string;
  nextOnAccept?: string;
  nextOnReject?: string;
  source?: ParallelItemSource;
  maxIterations?: number;
  gate?: string;
  gateDescription?: string;
}

export interface StepExecutionResult {
  stepId: string;
  agentId: string;
  type: WorkflowStepType;
  status: "completed" | "failed" | "paused";
  state: WorkflowData;
  error?: string;
}

export interface WorkflowEvent {
  type:
    | "step_start"
    | "step_complete"
    | "step_error"
    | "gate_requested"
    | "human_requested"
    | "action_proposed"
    | "action_error"
    | "approval"
    | "checkpoint_saved"
    | "agent_spawned"
    | "delegation_started"
    | "delegation_completed"
    | "delegation_failed";
  stepId: string;
  agentId: string;
  state: WorkflowData;
  error?: string;
  gateId?: string;
  gateDescription?: string;
  prompt?: string;
  proposedActions?: ActionProposal[];
  failedActions?: ActionRecord[];
  rollbackRecord?: RollbackRecord;
  actionPolicy?: ActionPolicy;
  checkpointId?: string;
  sessionId?: string;
  archetype?: string;
  spawnedBy?: string;
  delegatedBy?: string;
  delegateTo?: string;
  task?: string;
  depth?: number;
  resultSummary?: string;
}

export interface PendingGate {
  stepId: string;
  agentId: string;
  gateId: string;
  description: string;
}

export interface PendingHumanInput {
  stepId: string;
  agentId: string;
  prompt: string;
}

export interface PendingActionApproval {
  stepId: string;
  agentId: string;
  proposedActions: ActionProposal[];
  policy: ActionPolicy;
  output?: unknown;
}

export interface PendingActionError {
  stepId: string;
  agentId: string;
  failedActions: ActionRecord[];
  policy: ActionPolicy;
  output?: unknown;
  rollbackRecord?: RollbackRecord;
}

export interface SubWorkflowPauseContext {
  team: string;
  pausedResult: WorkflowResult;
}

export interface WorkflowPauseContext {
  stepId: string;
  stepIndex: number;
  agentId: string;
  reason: WorkflowPauseReason;
  iterationCounts: Record<string, number>;
  subWorkflow?: SubWorkflowPauseContext;
}

export interface WorkflowResult {
  status: WorkflowStatus;
  state: WorkflowData;
  stepResults: StepExecutionResult[];
  error?: string;
  pendingGate?: PendingGate;
  pendingHumanInput?: PendingHumanInput;
  pendingActionApproval?: PendingActionApproval;
  pendingActionError?: PendingActionError;
  pauseContext?: WorkflowPauseContext;
  checkpointId?: string;
}

export interface WorkflowEngineOptions {
  steps: WorkflowStep[];
  subWorkflows?: Record<string, SubWorkflowDefinition>;
}

export interface SubWorkflowDefinition {
  workflow: WorkflowEngine;
  agents: Record<string, Agent>;
}

export interface ExecuteWorkflowOptions {
  agents: Record<string, Agent>;
  initialState?: WorkflowData;
  checkpointStorage?: CheckpointStorage;
  sessionId?: string;
  workflowDefinition?: WorkflowDefinition;
}

export interface ResumeWorkflowOptions {
  agents: Record<string, Agent>;
  pausedResult: WorkflowResult;
  responses?: WorkflowData;
  checkpointStorage?: CheckpointStorage;
  sessionId?: string;
  workflowDefinition?: WorkflowDefinition;
}

type WorkflowEventHandler = (event: WorkflowEvent) => void | Promise<void>;

type CompletedStepExecution = {
  kind: "completed";
  state: WorkflowState;
};

type PausedStepExecution = {
  kind: "paused";
  pausedResult: WorkflowResult;
};

type StepExecutionOutcome = CompletedStepExecution | PausedStepExecution;

export class WorkflowEngine {
  private readonly steps: WorkflowStep[];
  private readonly stepMap: Map<string, WorkflowStep>;
  private readonly subWorkflows: Map<string, SubWorkflowDefinition>;
  private readonly eventHandlers: WorkflowEventHandler[] = [];

  constructor(options: WorkflowEngineOptions) {
    if (options.steps.length === 0) {
      throw new Error("WorkflowEngine requires at least one step.");
    }

    const seenStepIds = new Set<string>();
    for (const step of options.steps) {
      if (seenStepIds.has(step.id)) {
        throw new Error(`Duplicate workflow step id '${step.id}'.`);
      }
      seenStepIds.add(step.id);
    }

    this.steps = options.steps;
    this.stepMap = new Map(options.steps.map((step) => [step.id, step]));
    this.subWorkflows = new Map(Object.entries(options.subWorkflows ?? {}));
  }

  onEvent(handler: WorkflowEventHandler): () => void {
    this.eventHandlers.push(handler);

    return () => {
      const index = this.eventHandlers.indexOf(handler);
      if (index >= 0) {
        this.eventHandlers.splice(index, 1);
      }
    };
  }

  async emitRuntimeEvent(event: WorkflowEvent): Promise<void> {
    await this.emit(event);
  }

  async execute(options: ExecuteWorkflowOptions): Promise<WorkflowResult> {
    if (options.checkpointStorage && !options.sessionId) {
      throw new Error("WorkflowEngine.execute requires sessionId when checkpointStorage is set.");
    }

    const request = {
      agents: options.agents,
      state: new WorkflowState(options.initialState ?? {}),
      stepResults: [],
      currentStep: this.steps[0],
      visitedConditionals: new Map<string, number>(),
      subWorkflowDepth: 0
    } as {
      agents: Record<string, Agent>;
      state: WorkflowState;
      stepResults: StepExecutionResult[];
      currentStep: WorkflowStep | undefined;
      visitedConditionals: Map<string, number>;
      subWorkflowDepth: number;
      checkpointStorage?: CheckpointStorage;
      sessionId?: string;
      workflowDefinition?: WorkflowDefinition;
    };

    if (options.checkpointStorage) {
      request.checkpointStorage = options.checkpointStorage;
    }

    if (options.sessionId) {
      request.sessionId = options.sessionId;
    }

    if (options.workflowDefinition) {
      request.workflowDefinition = options.workflowDefinition;
    }

    return this.executeLoop(request);
  }

  async resume(options: ResumeWorkflowOptions): Promise<WorkflowResult> {
    if (options.checkpointStorage && !options.sessionId) {
      throw new Error("WorkflowEngine.resume requires sessionId when checkpointStorage is set.");
    }

    const pauseContext = options.pausedResult.pauseContext;
    if (options.pausedResult.status !== "paused" || !pauseContext) {
      throw new Error("WorkflowEngine.resume requires a paused workflow result with pauseContext.");
    }

    const currentStep = this.steps[pauseContext.stepIndex];
    if (!currentStep || currentStep.id !== pauseContext.stepId) {
      throw new Error(
        `Paused workflow references unknown step '${pauseContext.stepId}' at index ${pauseContext.stepIndex}.`
      );
    }

    const visitedConditionals = new Map<string, number>(
      Object.entries(pauseContext.iterationCounts)
    );

    if (pauseContext.subWorkflow) {
      return this.resumeSubWorkflow({
        agents: options.agents,
        currentStep,
        pausedResult: options.pausedResult,
        responses: options.responses ?? {},
        visitedConditionals,
        ...(options.checkpointStorage ? { checkpointStorage: options.checkpointStorage } : {}),
        ...(options.sessionId ? { sessionId: options.sessionId } : {}),
        ...(options.workflowDefinition
          ? { workflowDefinition: options.workflowDefinition }
          : {})
      });
    }

    const restoredState = this.restoreResumedState(
      pauseContext,
      currentStep,
      options.pausedResult.state,
      options.responses ?? {}
    );
    await this.emit({
      type: "approval",
      stepId: currentStep.id,
      agentId: currentStep.agent,
      state: restoredState
    });
    const nextStep =
      pauseContext.reason === "action_approval"
        ? currentStep
        : this.resolveNextStep(currentStep, restoredState, visitedConditionals);

    const request = {
      agents: options.agents,
      state: new WorkflowState(restoredState),
      stepResults: [...options.pausedResult.stepResults],
      currentStep: nextStep,
      visitedConditionals,
      subWorkflowDepth: 0
    } as {
      agents: Record<string, Agent>;
      state: WorkflowState;
      stepResults: StepExecutionResult[];
      currentStep: WorkflowStep | undefined;
      visitedConditionals: Map<string, number>;
      subWorkflowDepth: number;
      checkpointStorage?: CheckpointStorage;
      sessionId?: string;
      workflowDefinition?: WorkflowDefinition;
    };

    if (options.checkpointStorage) {
      request.checkpointStorage = options.checkpointStorage;
    }

    if (options.sessionId) {
      request.sessionId = options.sessionId;
    }

    if (options.workflowDefinition) {
      request.workflowDefinition = options.workflowDefinition;
    }

    return this.executeLoop(request);
  }

  private async executeLoop(options: {
    agents: Record<string, Agent>;
    state: WorkflowState;
    stepResults: StepExecutionResult[];
    currentStep: WorkflowStep | undefined;
    visitedConditionals: Map<string, number>;
    subWorkflowDepth: number;
    checkpointStorage?: CheckpointStorage;
    sessionId?: string;
    workflowDefinition?: WorkflowDefinition;
  }): Promise<WorkflowResult> {
    let { state, stepResults, currentStep } = options;
    const {
      agents,
      visitedConditionals,
      subWorkflowDepth,
      checkpointStorage,
      sessionId,
      workflowDefinition
    } = options;

    while (currentStep) {
      const step = currentStep;

      if (step.type === "gated") {
        const gateId = step.gate ?? step.id;
        const gateDescription = step.gateDescription ?? "";
        const pausedState = state.merge({
          awaitingGateApproval: true,
          awaiting_gate_approval: true,
          pendingGateId: gateId,
          pending_gate_id: gateId,
          pendingGateDescription: gateDescription,
          pending_gate_description: gateDescription,
          pendingGateStepId: step.id,
          pendingGateAgentId: step.agent
        });
        const snapshot = pausedState.snapshot();
        const pendingGate: PendingGate = {
          stepId: step.id,
          agentId: step.agent,
          gateId,
          description: gateDescription
        };

        await this.emit({
          type: "step_start",
          stepId: step.id,
          agentId: step.agent,
          state: state.snapshot()
        });
        await this.emit({
          type: "gate_requested",
          stepId: step.id,
          agentId: step.agent,
          state: snapshot,
          gateId,
          gateDescription
        });

        stepResults.push({
          stepId: step.id,
          agentId: step.agent,
          type: step.type,
          status: "paused",
          state: snapshot
        });

        let pausedResult: WorkflowResult = {
          status: "paused",
          state: snapshot,
          stepResults,
          pendingGate,
          pauseContext: this.buildPauseContext(step, "gated", visitedConditionals)
        };

        const checkpointRequest = {
          pausedResult,
          stepId: step.id,
          agentId: step.agent
        } as {
          pausedResult: WorkflowResult;
          checkpointStorage?: CheckpointStorage;
          sessionId?: string;
          stepId: string;
          agentId: string;
          workflowDefinition?: WorkflowDefinition;
        };

        if (checkpointStorage) {
          checkpointRequest.checkpointStorage = checkpointStorage;
        }

        if (sessionId) {
          checkpointRequest.sessionId = sessionId;
        }

        if (workflowDefinition) {
          checkpointRequest.workflowDefinition = workflowDefinition;
        }

        pausedResult = await this.persistCheckpoint(checkpointRequest);

        return pausedResult;
      }

      const agent = step.type === "sub_workflow" ? undefined : agents[step.agent];
      if (step.type !== "sub_workflow" && !agent) {
        return {
          status: "failed",
          state: state.snapshot(),
          stepResults,
          error: `Agent '${step.agent}' is not registered for workflow step '${step.id}'.`
        };
      }

      await this.emit({
        type: "step_start",
        stepId: step.id,
        agentId: agent?.id ?? step.agent,
        state: state.snapshot()
      });

      try {
        const execution = await this.executeStep(step, agent, state, subWorkflowDepth);

        if (execution.kind === "paused") {
          let pausedResult = this.buildSubWorkflowPausedResult({
            step,
            parentState: state.snapshot(),
            stepResults,
            nestedPausedResult: execution.pausedResult,
            visitedConditionals
          });

          const checkpointRequest = {
            pausedResult,
            stepId: step.id,
            agentId: step.agent
          } as {
            pausedResult: WorkflowResult;
            checkpointStorage?: CheckpointStorage;
            sessionId?: string;
            stepId: string;
            agentId: string;
            workflowDefinition?: WorkflowDefinition;
          };

          if (checkpointStorage) {
            checkpointRequest.checkpointStorage = checkpointStorage;
          }

          if (sessionId) {
            checkpointRequest.sessionId = sessionId;
          }

          if (workflowDefinition) {
            checkpointRequest.workflowDefinition = workflowDefinition;
          }

          pausedResult = await this.persistCheckpoint(checkpointRequest);

          return pausedResult;
        }

        state = execution.state;
        const snapshot = state.snapshot();

        if (step.type === "human_gate" && agent && this.isAwaitingHumanInput(snapshot)) {
          const prompt = this.resolveHumanPrompt(agent, snapshot);
          const pendingHumanInput: PendingHumanInput = {
            stepId: step.id,
            agentId: agent.id,
            prompt
          };

          await this.emit({
            type: "human_requested",
            stepId: step.id,
            agentId: agent.id,
            state: snapshot,
            prompt
          });

          stepResults.push({
            stepId: step.id,
            agentId: agent.id,
            type: step.type,
            status: "paused",
            state: snapshot
          });

          let pausedResult: WorkflowResult = {
            status: "paused",
            state: snapshot,
            stepResults,
            pendingHumanInput,
            pauseContext: this.buildPauseContext(step, "human_gate", visitedConditionals)
          };

          const checkpointRequest = {
            pausedResult,
            stepId: step.id,
            agentId: agent.id
          } as {
            pausedResult: WorkflowResult;
            checkpointStorage?: CheckpointStorage;
            sessionId?: string;
            stepId: string;
            agentId: string;
            workflowDefinition?: WorkflowDefinition;
          };

          if (checkpointStorage) {
            checkpointRequest.checkpointStorage = checkpointStorage;
          }

          if (sessionId) {
            checkpointRequest.sessionId = sessionId;
          }

          if (workflowDefinition) {
            checkpointRequest.workflowDefinition = workflowDefinition;
          }

          pausedResult = await this.persistCheckpoint(checkpointRequest);

          return pausedResult;
        }

        if (agent && this.isAwaitingActionApproval(snapshot)) {
          const pendingActionApproval = this.resolvePendingActionApproval(step, agent, snapshot);

          await this.emit({
            type: "action_proposed",
            stepId: step.id,
            agentId: agent.id,
            state: snapshot,
            proposedActions: pendingActionApproval.proposedActions,
            actionPolicy: pendingActionApproval.policy
          });

          stepResults.push({
            stepId: step.id,
            agentId: agent.id,
            type: step.type,
            status: "paused",
            state: snapshot
          });

          let pausedResult: WorkflowResult = {
            status: "paused",
            state: snapshot,
            stepResults,
            pendingActionApproval,
            pauseContext: this.buildPauseContext(step, "action_approval", visitedConditionals)
          };

          const checkpointRequest = {
            pausedResult,
            stepId: step.id,
            agentId: agent.id
          } as {
            pausedResult: WorkflowResult;
            checkpointStorage?: CheckpointStorage;
            sessionId?: string;
            stepId: string;
            agentId: string;
            workflowDefinition?: WorkflowDefinition;
          };

          if (checkpointStorage) {
            checkpointRequest.checkpointStorage = checkpointStorage;
          }

          if (sessionId) {
            checkpointRequest.sessionId = sessionId;
          }

          if (workflowDefinition) {
            checkpointRequest.workflowDefinition = workflowDefinition;
          }

          pausedResult = await this.persistCheckpoint(checkpointRequest);

          return pausedResult;
        }

        if (agent && this.isAwaitingActionError(snapshot)) {
          const pendingActionError = this.resolvePendingActionError(step, agent, snapshot);

          await this.emit({
            type: "action_error",
            stepId: step.id,
            agentId: agent.id,
            state: snapshot,
            failedActions: pendingActionError.failedActions,
            ...(pendingActionError.rollbackRecord
              ? { rollbackRecord: pendingActionError.rollbackRecord }
              : {}),
            actionPolicy: pendingActionError.policy,
            error: "Action executor requires error acknowledgement before continuing."
          });

          stepResults.push({
            stepId: step.id,
            agentId: agent.id,
            type: step.type,
            status: "paused",
            state: snapshot
          });

          let pausedResult: WorkflowResult = {
            status: "paused",
            state: snapshot,
            stepResults,
            pendingActionError,
            pauseContext: this.buildPauseContext(step, "action_error", visitedConditionals)
          };

          const checkpointRequest = {
            pausedResult,
            stepId: step.id,
            agentId: agent.id
          } as {
            pausedResult: WorkflowResult;
            checkpointStorage?: CheckpointStorage;
            sessionId?: string;
            stepId: string;
            agentId: string;
            workflowDefinition?: WorkflowDefinition;
          };

          if (checkpointStorage) {
            checkpointRequest.checkpointStorage = checkpointStorage;
          }

          if (sessionId) {
            checkpointRequest.sessionId = sessionId;
          }

          if (workflowDefinition) {
            checkpointRequest.workflowDefinition = workflowDefinition;
          }

          pausedResult = await this.persistCheckpoint(checkpointRequest);

          return pausedResult;
        }

        const nextStep = this.resolveNextStep(step, snapshot, visitedConditionals);

        stepResults.push({
          stepId: step.id,
          agentId: agent?.id ?? step.agent,
          type: step.type,
          status: "completed",
          state: snapshot
        });

        await this.emit({
          type: "step_complete",
          stepId: step.id,
          agentId: agent?.id ?? step.agent,
          state: snapshot
        });

        currentStep = nextStep;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const snapshot = state.snapshot();

        stepResults.push({
          stepId: step.id,
          agentId: agent?.id ?? step.agent,
          type: step.type,
          status: "failed",
          state: snapshot,
          error: message
        });

        await this.emit({
          type: "step_error",
          stepId: step.id,
          agentId: agent?.id ?? step.agent,
          state: snapshot,
          error: message
        });

        return {
          status: "failed",
          state: snapshot,
          stepResults,
          error: message
        };
      }
    }

    return {
      status: "completed",
      state: state.snapshot(),
      stepResults
    };
  }

  private async executeStep(
    step: WorkflowStep,
    agent: Agent | undefined,
    state: WorkflowState,
    subWorkflowDepth: number
  ): Promise<StepExecutionOutcome> {
    switch (step.type) {
      case "sequential":
      case "conditional":
      case "human_gate":
        if (!agent) {
          throw new Error(`Workflow step '${step.id}' requires an agent instance.`);
        }
        return {
          kind: "completed",
          state: await this.executeSingleAgentStep(step, agent, state)
        };
      case "parallel_fan_out":
        if (!agent) {
          throw new Error(`Workflow step '${step.id}' requires an agent instance.`);
        }
        return {
          kind: "completed",
          state: await this.executeParallelFanOutStep(step, agent, state)
        };
      case "sub_workflow":
        return this.executeSubWorkflowStep(step, state, subWorkflowDepth);
      default:
        throw new Error(
          `Workflow step type '${step.type}' is not implemented in the current TypeScript bootstrap.`
        );
    }
  }

  private async executeSubWorkflowStep(
    step: WorkflowStep,
    state: WorkflowState,
    subWorkflowDepth: number
  ): Promise<StepExecutionOutcome> {
    if (!step.team) {
      throw new Error(`Workflow step '${step.id}' must define 'team' for sub_workflow.`);
    }

    if (subWorkflowDepth >= DEFAULT_MAX_SUB_WORKFLOW_DEPTH) {
      throw new Error(
        `Sub-workflow recursion depth exceeded (${DEFAULT_MAX_SUB_WORKFLOW_DEPTH}) at step '${step.id}'.`
      );
    }

    const subWorkflow = this.subWorkflows.get(step.team);
    if (!subWorkflow) {
      throw new Error(`Sub-workflow team '${step.team}' is not registered.`);
    }

    const parentState = state.snapshot();
    const innerInitialState = this.buildSubWorkflowInitialState(step, parentState);
    const dispose = subWorkflow.workflow.onEvent((event) => this.emit(event));
    let result: WorkflowResult;

    try {
      result = await subWorkflow.workflow.executeLoop({
        agents: subWorkflow.agents,
        state: new WorkflowState(innerInitialState),
        stepResults: [],
        currentStep: subWorkflow.workflow.steps[0],
        visitedConditionals: new Map<string, number>(),
        subWorkflowDepth: subWorkflowDepth + 1
      });
    } finally {
      dispose();
    }

    if (result.status === "paused") {
      return {
        kind: "paused",
        pausedResult: result
      };
    }

    if (result.status !== "completed") {
      throw new Error(`Sub-workflow '${step.team}' failed: ${result.error ?? result.status}`);
    }

    return {
      kind: "completed",
      state: state.merge(this.buildSubWorkflowOutputPatch(step, result.state))
    };
  }

  private buildSubWorkflowInitialState(
    step: WorkflowStep,
    parentState: WorkflowData
  ): WorkflowData {
    if (!step.inputMapping || Object.keys(step.inputMapping).length === 0) {
      return { ...parentState };
    }

    return Object.fromEntries(
      Object.entries(step.inputMapping).map(([innerKey, outerKey]) => [innerKey, parentState[outerKey]])
    );
  }

  private buildSubWorkflowOutputPatch(
    step: WorkflowStep,
    subWorkflowState: WorkflowData
  ): WorkflowData {
    if (!step.outputMapping || Object.keys(step.outputMapping).length === 0) {
      return subWorkflowState;
    }

    return Object.fromEntries(
      Object.entries(step.outputMapping).map(([outerKey, innerKey]) => [outerKey, subWorkflowState[innerKey]])
    );
  }

  private async executeSingleAgentStep(
    step: WorkflowStep,
    agent: Agent,
    state: WorkflowState
  ): Promise<WorkflowState> {
    const execution = await agent.execute(state.snapshot(), { stepId: step.id });
    return state.merge(execution.statePatch);
  }

  private async executeParallelFanOutStep(
    step: WorkflowStep,
    agent: Agent,
    state: WorkflowState
  ): Promise<WorkflowState> {
    const snapshot = state.snapshot();
    const parallelItems = this.resolveParallelItems(step, snapshot);

    if (!parallelItems || parallelItems.length === 0) {
      return this.executeSingleAgentStep(step, agent, state);
    }

    const executions = await Promise.allSettled(
      parallelItems.map((item, index) =>
        agent.execute(this.buildParallelItemState(snapshot, item, index), { stepId: step.id })
      )
    );

    const outputs: unknown[] = [];
    const parallelResults: Record<string, unknown> = {};
    const finishReasons: string[] = [];
    const usages: TokenUsage[] = [];
    const errors: string[] = [];

    for (const [index, execution] of executions.entries()) {
      const itemKey = `item_${index}`;
      const currentItem = parallelItems[index];

      if (execution.status === "fulfilled") {
        const usage = execution.value.statePatch[`${agent.id}Usage`];
        const finishReason = execution.value.statePatch[`${agent.id}FinishReason`];

        outputs.push(execution.value.output);
        parallelResults[itemKey] = {
          currentItem,
          itemIndex: index,
          output: execution.value.output,
          prompt: execution.value.prompt,
          statePatch: execution.value.statePatch
        };

        if (isTokenUsage(usage)) {
          usages.push(usage);
        }

        if (typeof finishReason === "string" && finishReason.length > 0) {
          finishReasons.push(finishReason);
        }

        continue;
      }

      const message = execution.reason instanceof Error
        ? execution.reason.message
        : String(execution.reason);

      outputs.push({ error: message });
      parallelResults[itemKey] = {
        currentItem,
        itemIndex: index,
        error: message
      };
      errors.push(message);
      finishReasons.push("error");
    }

    const textOutputs = outputs.filter(
      (output): output is string => typeof output === "string" && output.length > 0
    );
    const combinedOutput = textOutputs.join("\n\n");
    const statePatch: WorkflowData = {
      [`${agent.id}Outputs`]: outputs,
      [`${agent.id}ParallelResults`]: parallelResults,
      [`${agent.id}Output`]: combinedOutput,
      lastAgentId: agent.id,
      lastOutput: combinedOutput.length > 0 ? combinedOutput : outputs
    };
    const usage = aggregateTokenUsage(usages);
    const finishReason = resolveParallelFinishReason(finishReasons);

    if (usage) {
      statePatch[`${agent.id}Usage`] = usage;
    }

    if (finishReason) {
      statePatch[`${agent.id}FinishReason`] = finishReason;
    }

    if (errors.length > 0) {
      statePatch[`${agent.id}Errors`] = errors;
    }

    return state.merge(statePatch);
  }

  private resolveParallelItems(
    step: WorkflowStep,
    state: WorkflowData
  ): unknown[] | undefined {
    if (step.source === "taskData") {
      return asArray(state.taskData ?? state.task_data);
    }

    if (step.source === "task_data") {
      return asArray(state.task_data ?? state.taskData);
    }

    if (step.source === "parallel_items") {
      return asArray(state.parallel_items ?? state.parallelItems);
    }

    return asArray(state.parallelItems ?? state.parallel_items);
  }

  private buildParallelItemState(
    baseState: WorkflowData,
    item: unknown,
    index: number
  ): WorkflowData {
    return {
      ...baseState,
      currentItem: item,
      current_item: item,
      itemIndex: index,
      item_index: index
    };
  }

  private resolveNextStep(
    step: WorkflowStep,
    state: WorkflowData,
    visitedConditionals: Map<string, number>
  ): WorkflowStep | undefined {
    let nextStepId = step.next;

    if (step.type === "conditional") {
      const conditionAccepted = this.evaluateCondition(step.agent, state);
      const visitCount = (visitedConditionals.get(step.id) ?? 0) + 1;
      const maxIterations =
        typeof step.maxIterations === "number" && step.maxIterations > 0
          ? step.maxIterations
          : DEFAULT_MAX_CONDITIONAL_ITERATIONS;

      visitedConditionals.set(step.id, visitCount);

      if (visitCount > maxIterations) {
        throw new Error(
          `Conditional loop for '${step.id}' exceeded maximum iterations (${maxIterations}).`
        );
      }

      nextStepId = conditionAccepted
        ? (step.nextOnAccept ?? step.next)
        : (step.nextOnReject ?? step.next);
    }

    if (nextStepId) {
      const targetStep = this.stepMap.get(nextStepId);
      if (!targetStep) {
        throw new Error(`Workflow step '${step.id}' points to missing next step '${nextStepId}'.`);
      }
      return targetStep;
    }

    const currentIndex = this.steps.findIndex((currentStep) => currentStep.id === step.id);
    if (currentIndex === -1) {
      throw new Error(`Workflow step '${step.id}' is not part of the active workflow.`);
    }

    return this.steps[currentIndex + 1];
  }

  private evaluateCondition(agentId: string, state: WorkflowData): boolean {
    if (state[`${agentId}Approved`] === true || state[`${agentId}_approved`] === true) {
      return true;
    }

    if (state[`${agentId}Rejected`] === true || state[`${agentId}_rejected`] === true) {
      return false;
    }

    const output = toSearchableText(state[`${agentId}Output`] ?? state[`${agentId}_output`]);
    const normalizedOutput = output.toLowerCase();
    const acceptKeywords = ["approved", "accepted", "pass", "satisfactory", "meets criteria"];
    const rejectKeywords = ["rejected", "needs revision", "revise", "insufficient", "fail"];

    const acceptScore = acceptKeywords.reduce(
      (total, keyword) => total + (normalizedOutput.includes(keyword) ? 1 : 0),
      0
    );
    const rejectScore = rejectKeywords.reduce(
      (total, keyword) => total + (normalizedOutput.includes(keyword) ? 1 : 0),
      0
    );

    return acceptScore > rejectScore;
  }

  private isAwaitingHumanInput(state: WorkflowData): boolean {
    return state.awaitingHumanInput === true || state.awaiting_human_input === true;
  }

  private isAwaitingActionApproval(state: WorkflowData): boolean {
    return state.awaitingActionApproval === true || state.awaiting_action_approval === true;
  }

  private isAwaitingActionError(state: WorkflowData): boolean {
    return state.awaitingActionError === true || state.awaiting_action_error === true;
  }

  private resolveHumanPrompt(agent: Agent, state: WorkflowData): string {
    const prompt = state.humanPrompt ?? state.human_prompt;
    if (typeof prompt === "string" && prompt.length > 0) {
      return prompt;
    }

    return `Agent '${agent.role}' requires your input.`;
  }

  private resolvePendingActionApproval(
    step: WorkflowStep,
    agent: Agent,
    state: WorkflowData
  ): PendingActionApproval {
    const proposedActions = normalizeActionProposals(
      state[`${agent.id}ProposedActions`] ?? state[`${agent.id}_proposed_actions`]
    );

    if (proposedActions.length === 0) {
      throw new Error(
        `Action executor '${agent.id}' paused for approval without any proposed actions.`
      );
    }

    return {
      stepId: step.id,
      agentId: agent.id,
      proposedActions,
      policy: "require_approval",
      output: state[`${agent.id}Output`] ?? state[`${agent.id}_output`]
    };
  }

  private resolvePendingActionError(
    step: WorkflowStep,
    agent: Agent,
    state: WorkflowData
  ): PendingActionError {
    const failedActions = normalizeActionRecords(
      state[`${agent.id}FailedActions`] ?? state[`${agent.id}_failed_actions`]
    ).filter((record) => record.status === "error");
    const actionErrorDetails =
      state[`${agent.id}ActionErrorDetails`] ?? state[`${agent.id}_action_error_details`];
    const rollbackRecord = normalizeActionErrorRollbackRecord(actionErrorDetails);

    if (failedActions.length === 0) {
      throw new Error(
        `Action executor '${agent.id}' paused for error acknowledgement without any failed actions.`
      );
    }

    return {
      stepId: step.id,
      agentId: agent.id,
      failedActions,
      policy: "confirm_on_error",
      output: state[`${agent.id}Output`] ?? state[`${agent.id}_output`],
      ...(rollbackRecord ? { rollbackRecord } : {})
    };
  }

  private buildPauseContext(
    step: WorkflowStep,
    reason: WorkflowPauseReason,
    visitedConditionals: Map<string, number>,
    subWorkflow?: SubWorkflowPauseContext
  ): WorkflowPauseContext {
    const stepIndex = this.steps.findIndex((candidate) => candidate.id === step.id);
    if (stepIndex === -1) {
      throw new Error(`Workflow step '${step.id}' is not part of the active workflow.`);
    }

    return {
      stepId: step.id,
      stepIndex,
      agentId: step.agent,
      reason,
      iterationCounts: Object.fromEntries(visitedConditionals),
      ...(subWorkflow ? { subWorkflow } : {})
    };
  }

  private buildSubWorkflowPausedResult(options: {
    step: WorkflowStep;
    parentState: WorkflowData;
    stepResults: StepExecutionResult[];
    nestedPausedResult: WorkflowResult;
    visitedConditionals: Map<string, number>;
  }): WorkflowResult {
    const { step, parentState, stepResults, nestedPausedResult, visitedConditionals } = options;
    if (!step.team) {
      throw new Error(`Workflow step '${step.id}' must define 'team' for sub_workflow.`);
    }

    if (nestedPausedResult.status !== "paused" || !nestedPausedResult.pauseContext) {
      throw new Error(
        `Sub-workflow '${step.team}' did not provide pause metadata for parent step '${step.id}'.`
      );
    }

    return {
      status: "paused",
      state: parentState,
      stepResults: [
        ...stepResults,
        {
          stepId: step.id,
          agentId: step.agent,
          type: step.type,
          status: "paused",
          state: parentState
        }
      ],
      ...(nestedPausedResult.pendingGate ? { pendingGate: nestedPausedResult.pendingGate } : {}),
      ...(nestedPausedResult.pendingHumanInput
        ? { pendingHumanInput: nestedPausedResult.pendingHumanInput }
        : {}),
      ...(nestedPausedResult.pendingActionApproval
        ? { pendingActionApproval: nestedPausedResult.pendingActionApproval }
        : {}),
      ...(nestedPausedResult.pendingActionError
        ? { pendingActionError: nestedPausedResult.pendingActionError }
        : {}),
      pauseContext: this.buildPauseContext(
        step,
        nestedPausedResult.pauseContext.reason,
        visitedConditionals,
        {
          team: step.team,
          pausedResult: nestedPausedResult
        }
      )
    };
  }

  private async resumeSubWorkflow(options: {
    agents: Record<string, Agent>;
    currentStep: WorkflowStep;
    pausedResult: WorkflowResult;
    responses: WorkflowData;
    visitedConditionals: Map<string, number>;
    checkpointStorage?: CheckpointStorage;
    sessionId?: string;
    workflowDefinition?: WorkflowDefinition;
  }): Promise<WorkflowResult> {
    const {
      agents,
      currentStep,
      pausedResult,
      responses,
      visitedConditionals,
      checkpointStorage,
      sessionId,
      workflowDefinition
    } = options;

    if (currentStep.type !== "sub_workflow" || !currentStep.team) {
      throw new Error(
        `Workflow step '${currentStep.id}' is not a resumable sub_workflow step.`
      );
    }

    const subWorkflowPause = pausedResult.pauseContext?.subWorkflow;
    if (!subWorkflowPause) {
      throw new Error(
        `Workflow step '${currentStep.id}' is missing nested sub-workflow pause metadata.`
      );
    }

    const subWorkflow = this.subWorkflows.get(subWorkflowPause.team);
    if (!subWorkflow) {
      throw new Error(`Sub-workflow team '${subWorkflowPause.team}' is not registered.`);
    }

    const parentState = this.mergeResumeResponses(pausedResult.state, responses);
    const dispose = subWorkflow.workflow.onEvent((event) => this.emit(event));

    try {
      const nestedResult = await subWorkflow.workflow.resume({
        agents: subWorkflow.agents,
        pausedResult: subWorkflowPause.pausedResult,
        responses
      });

      if (nestedResult.status === "paused") {
        let nextPausedResult = this.buildSubWorkflowPausedResult({
          step: currentStep,
          parentState,
          stepResults: pausedResult.stepResults,
          nestedPausedResult: nestedResult,
          visitedConditionals
        });

        nextPausedResult = await this.persistCheckpoint({
          pausedResult: nextPausedResult,
          stepId: currentStep.id,
          agentId: currentStep.agent,
          ...(checkpointStorage ? { checkpointStorage } : {}),
          ...(sessionId ? { sessionId } : {}),
          ...(workflowDefinition ? { workflowDefinition } : {})
        });

        return nextPausedResult;
      }

      if (nestedResult.status !== "completed") {
        const error = `Sub-workflow '${subWorkflowPause.team}' failed: ${nestedResult.error ?? nestedResult.status}`;
        const stepResults: StepExecutionResult[] = [
          ...pausedResult.stepResults,
          {
            stepId: currentStep.id,
            agentId: currentStep.agent,
            type: currentStep.type,
            status: "failed",
            state: parentState,
            error
          }
        ];
        const failedResult: WorkflowResult = {
          status: "failed",
          state: parentState,
          stepResults,
          error
        };

        await this.emit({
          type: "step_error",
          stepId: currentStep.id,
          agentId: currentStep.agent,
          state: parentState,
          error
        });

        return failedResult;
      }

      const resumedState = new WorkflowState(parentState).merge(
        this.buildSubWorkflowOutputPatch(currentStep, nestedResult.state)
      );
      const snapshot = resumedState.snapshot();
      const nextStep = this.resolveNextStep(currentStep, snapshot, visitedConditionals);
      const stepResults: StepExecutionResult[] = [
        ...pausedResult.stepResults,
        {
          stepId: currentStep.id,
          agentId: currentStep.agent,
          type: currentStep.type,
          status: "completed",
          state: snapshot
        }
      ];

      await this.emit({
        type: "step_complete",
        stepId: currentStep.id,
        agentId: currentStep.agent,
        state: snapshot
      });

      return this.executeLoop({
        agents,
        state: resumedState,
        stepResults,
        currentStep: nextStep,
        visitedConditionals,
        subWorkflowDepth: 0,
        ...(checkpointStorage ? { checkpointStorage } : {}),
        ...(sessionId ? { sessionId } : {}),
        ...(workflowDefinition ? { workflowDefinition } : {})
      });
    } finally {
      dispose();
    }
  }

  private mergeResumeResponses(pausedState: WorkflowData, responses: WorkflowData): WorkflowData {
    return {
      ...pausedState,
      ...responses,
      resumeResponses: responses,
      resume_responses: responses
    };
  }

  private restoreResumedState(
    pauseContext: WorkflowPauseContext,
    currentStep: WorkflowStep,
    pausedState: WorkflowData,
    responses: WorkflowData
  ): WorkflowData {
    if (pauseContext.subWorkflow) {
      throw new Error(
        `WorkflowEngine.resume must delegate nested sub-workflow pause '${pauseContext.stepId}' through the nested workflow runtime.`
      );
    }

    const state = this.mergeResumeResponses(pausedState, responses);

    if (Object.keys(responses).length === 0) {
      throw new Error(
        `WorkflowEngine.resume requires responses to continue paused step '${pauseContext.stepId}'.`
      );
    }

    switch (pauseContext.reason) {
      case "gated":
        state.awaitingGateApproval = false;
        state.awaiting_gate_approval = false;
        delete state.pendingGateId;
        delete state.pending_gate_id;
        delete state.pendingGateDescription;
        delete state.pending_gate_description;
        delete state.pendingGateStepId;
        delete state.pendingGateAgentId;
        return state;
      case "human_gate": {
        state.awaitingHumanInput = false;
        state.awaiting_human_input = false;
        delete state.humanPrompt;
        delete state.human_prompt;
        delete state.pendingHumanAgentId;
        delete state.pending_human_agent_id;

        const humanInput = state.humanInput ?? state.human_input;
        if (humanInput === undefined || humanInput === null) {
          throw new Error(
            `WorkflowEngine.resume requires 'humanInput' or 'human_input' when resuming human-gate step '${pauseContext.stepId}'.`
          );
        }

        state[`${currentStep.agent}Output`] = humanInput;
        state[`${currentStep.agent}Approved`] = true;
        state[`${currentStep.agent}_approved`] = true;
        state.humanApproved = true;
        state.human_approved = true;
        state.lastAgentId = currentStep.agent;
        state.lastOutput = humanInput;
        return state;
      }
      case "action_approval":
        state.awaitingActionApproval = false;
        state.awaiting_action_approval = false;
        delete state.pendingActionAgentId;
        delete state.pending_action_agent_id;
        return state;
      case "action_error": {
        state.awaitingActionError = false;
        state.awaiting_action_error = false;
        delete state.pendingActionErrorAgentId;
        delete state.pending_action_error_agent_id;

        const acknowledged = firstBoolean([
          state[`${currentStep.agent}ActionErrorAcknowledged`],
          state[`${currentStep.agent}_action_error_acknowledged`],
          state.actionErrorAcknowledged,
          state.action_error_acknowledged
        ]);

        if (acknowledged !== true) {
          throw new Error(
            `WorkflowEngine.resume requires '${currentStep.agent}ActionErrorAcknowledged' or 'actionErrorAcknowledged' to be true when resuming action-error step '${pauseContext.stepId}'.`
          );
        }

        state[`${currentStep.agent}ActionErrorAcknowledged`] = true;
        state[`${currentStep.agent}_action_error_acknowledged`] = true;
        return state;
      }
      default:
        throw new Error(
          `WorkflowEngine.resume does not support pause reason '${pauseContext.reason}'.`
        );
    }
  }

  private async emit(event: WorkflowEvent): Promise<void> {
    for (const handler of this.eventHandlers) {
      await handler(event);
    }
  }

  private async persistCheckpoint(options: {
    pausedResult: WorkflowResult;
    checkpointStorage?: CheckpointStorage;
    sessionId?: string;
    stepId: string;
    agentId: string;
    workflowDefinition?: WorkflowDefinition;
  }): Promise<WorkflowResult> {
    const { pausedResult, checkpointStorage, sessionId, stepId, agentId, workflowDefinition } = options;

    if (!checkpointStorage) {
      return pausedResult;
    }

    if (!sessionId) {
      throw new Error("WorkflowEngine requires sessionId when checkpointStorage is set.");
    }

    const checkpointId = randomUUID();
    const checkpointedResult: WorkflowResult = {
      ...pausedResult,
      checkpointId
    };

    await checkpointStorage.save(
      createWorkflowCheckpoint({
        sessionId,
        checkpointId,
        pausedResult: checkpointedResult,
        ...(workflowDefinition ? { workflowDefinition } : {})
      })
    );

    await this.emit({
      type: "checkpoint_saved",
      stepId,
      agentId,
      state: checkpointedResult.state,
      checkpointId,
      sessionId
    });

    return checkpointedResult;
  }
}

function asArray(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function aggregateTokenUsage(usages: TokenUsage[]): TokenUsage | undefined {
  if (usages.length === 0) {
    return undefined;
  }

  return usages.reduce(
    (combined, usage) => ({
      inputTokens: combined.inputTokens + usage.inputTokens,
      outputTokens: combined.outputTokens + usage.outputTokens,
      totalTokens: combined.totalTokens + usage.totalTokens
    }),
    {
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0
    }
  );
}

function isTokenUsage(value: unknown): value is TokenUsage {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as TokenUsage).inputTokens === "number" &&
    typeof (value as TokenUsage).outputTokens === "number" &&
    typeof (value as TokenUsage).totalTokens === "number"
  );
}

function resolveParallelFinishReason(finishReasons: string[]): string | undefined {
  if (finishReasons.length === 0) {
    return undefined;
  }

  if (finishReasons.every((finishReason) => finishReason === finishReasons[0])) {
    return finishReasons[0];
  }

  if (finishReasons.includes("error")) {
    return "error";
  }

  return "parallel";
}

function toSearchableText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (value === undefined || value === null) {
    return "";
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function firstBoolean(values: unknown[]): boolean | undefined {
  for (const value of values) {
    if (typeof value === "boolean") {
      return value;
    }
  }

  return undefined;
}