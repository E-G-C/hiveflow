import type {
    ModelAdapter,
    ModelInvocationRequest,
    ModelInvocationResult,
    ToolExecutionMode,
    ToolDefinition
} from "./model.js";
import type { ModelMessage, ToolCall, ToolResult, WorkflowData } from "./types.js";
import {
    normalizeActionProposals,
    normalizeActionRecords,
    normalizeRollbackRecords
} from "./internal.js";

const DEFAULT_MAX_TOOL_ITERATIONS = 5;

export type AgentBehavior =
    | "llm_only"
    | "tool_user"
    | "orchestrator"
    | "human_gate"
    | "action_executor";

export type ActionPolicy = "auto" | "require_approval" | "dry_run" | "confirm_on_error";

export interface ActionProposal {
    tool: string;
    arguments: unknown;
    toolCallId: string;
}

export interface ActionRecord {
    actionId: string;
    agentId: string;
    tool: string;
    arguments: unknown;
    status: "completed" | "dry_run" | "error" | "rejected";
    policy: ActionPolicy;
    toolCallId: string;
    reversible?: boolean;
    rollbackAction?: string;
    result?: unknown;
}

export interface RollbackRecord {
    rollbackId: string;
    agentId: string;
    rollbackAction: string;
    status: "completed" | "error";
    failedActions: ActionRecord[];
    result?: unknown;
}

type PromptBuilder = string | ((state: Readonly<WorkflowData>) => string);

export interface AgentOptions {
    id: string;
    role: string;
    instructions: string;
    model: ModelAdapter;
    behavior?: AgentBehavior;
    prompt?: PromptBuilder;
    tools?: Record<string, ToolDefinition>;
    actionPolicy?: ActionPolicy;
    rollbackOnFailure?: boolean;
    rollbackAction?: string;
    temperature?: number;
    maxOutputTokens?: number;
    collaboration?: AgentCollaborationContext;
}

export interface AgentExecutionContext {
    stepId?: string;
}

export interface AgentCollaborationContext {
    listAgentIds(): string[];
    listArchetypes(): string[];
    createOrchestratorTools(agent: Agent): Record<string, ToolDefinition>;
}

export interface AgentExecutionResult {
    agentId: string;
    behavior: AgentBehavior;
    prompt: string;
    output: unknown;
    statePatch: WorkflowData;
    invocation: ModelInvocationResult;
}

const SUPPORTED_BEHAVIORS: ReadonlySet<AgentBehavior> = new Set([
    "llm_only",
    "tool_user",
    "orchestrator",
    "human_gate",
    "action_executor"
]);

export class Agent {
    private readonly behaviorType: AgentBehavior;

    constructor(private readonly options: AgentOptions) {
        this.behaviorType = options.behavior ?? "llm_only";
    }

    get id(): string {
        return this.options.id;
    }

    get role(): string {
        return this.options.role;
    }

    get instructions(): string {
        return this.options.instructions;
    }

    get model(): ModelAdapter {
        return this.options.model;
    }

    get behavior(): AgentBehavior {
        return this.behaviorType;
    }

    async execute(
        state: WorkflowData,
        executionContext: AgentExecutionContext = {}
    ): Promise<AgentExecutionResult> {
        if (!SUPPORTED_BEHAVIORS.has(this.behaviorType)) {
            throw new Error(
                `Behavior '${this.behaviorType}' is not implemented in the current TypeScript bootstrap.`
            );
        }

        const prompt = this.buildPrompt(state);

        if (this.behaviorType === "human_gate") {
            return this.executeHumanGate(state, prompt);
        }

        if (this.behaviorType === "action_executor") {
            return this.executeActionExecutor(state, prompt, executionContext);
        }

        if (this.behaviorType === "tool_user" || this.behaviorType === "orchestrator") {
            return this.executeToolEnabledAgent(state, prompt, executionContext);
        }

        const request = this.buildRequest(state, this.buildMessages(prompt));
        const invocation = await this.options.model.generate(request);
        const output = invocation.output ?? invocation.text;

        return this.createAgentExecutionResult(prompt, output, invocation);
    }

    private executeHumanGate(state: WorkflowData, prompt: string): AgentExecutionResult {
        const humanInput = state.humanInput ?? state.human_input;

        if (humanInput !== undefined && humanInput !== null) {
            return {
                agentId: this.options.id,
                behavior: this.behaviorType,
                prompt,
                output: humanInput,
                invocation: createSyntheticInvocation(humanInput),
                statePatch: {
                    [`${this.options.id}Output`]: humanInput,
                    [`${this.options.id}Approved`]: true,
                    [`${this.options.id}_approved`]: true,
                    humanApproved: true,
                    human_approved: true,
                    awaitingHumanInput: false,
                    awaiting_human_input: false,
                    lastAgentId: this.options.id,
                    lastOutput: humanInput
                }
            };
        }

        const humanPrompt = `Agent '${this.options.role}' requires your input.`;

        return {
            agentId: this.options.id,
            behavior: this.behaviorType,
            prompt,
            output: undefined,
            invocation: createSyntheticInvocation(humanPrompt),
            statePatch: {
                awaitingHumanInput: true,
                awaiting_human_input: true,
                humanPrompt,
                human_prompt: humanPrompt,
                pendingHumanAgentId: this.options.id,
                pending_human_agent_id: this.options.id,
                lastAgentId: this.options.id
            }
        };
    }

    private buildRequest(
        state: WorkflowData,
        messages: ModelMessage[],
        tools?: Record<string, ToolDefinition>,
        toolExecutionMode?: ToolExecutionMode
    ): ModelInvocationRequest {
        const request: ModelInvocationRequest = {
            messages,
            state
        };

        if (typeof this.options.temperature === "number") {
            request.temperature = this.options.temperature;
        }

        if (typeof this.options.maxOutputTokens === "number") {
            request.maxOutputTokens = this.options.maxOutputTokens;
        }

        if (tools && Object.keys(tools).length > 0) {
            request.tools = tools;
        }

        if (toolExecutionMode) {
            request.toolExecutionMode = toolExecutionMode;
        }

        return request;
    }

    private async executeToolEnabledAgent(
        state: WorkflowData,
        prompt: string,
        executionContext: AgentExecutionContext
    ): Promise<AgentExecutionResult> {
        const tools = this.resolveTools();
        if (!tools) {
            const invocation = await this.options.model.generate(
                this.buildRequest(state, this.buildMessages(prompt))
            );
            const output = invocation.output ?? invocation.text;

            return this.createAgentExecutionResult(prompt, output, invocation);
        }

        let messages = this.buildMessages(prompt);
        const executedToolCalls: ToolCall[] = [];
        const executedToolResults: ToolResult[] = [];

        for (let iteration = 0; iteration < DEFAULT_MAX_TOOL_ITERATIONS; iteration += 1) {
            const invocation = await this.options.model.generate(
                this.buildRequest(state, messages, tools, "manual")
            );

            if (invocation.toolCalls.length === 0) {
                const output = invocation.output ?? invocation.text;
                return this.createAgentExecutionResult(prompt, output, {
                    ...invocation,
                    toolCalls: [...executedToolCalls, ...invocation.toolCalls],
                    toolResults: [...executedToolResults, ...invocation.toolResults]
                });
            }

            const toolResults = await this.executeToolCalls(
                state,
                messages,
                tools,
                invocation.toolCalls,
                executionContext
            );
            executedToolCalls.push(...invocation.toolCalls);
            executedToolResults.push(...toolResults);

            messages = [
                ...messages,
                {
                    role: "assistant",
                    content: invocation.text,
                    toolCalls: invocation.toolCalls
                },
                ...toolResults.map((toolResult) => ({
                    role: "tool" as const,
                    name: toolResult.name,
                    toolCallId: toolResult.toolCallId,
                    content: serializeToolResult(toolResult.output)
                }))
            ];
        }

        throw new Error(
            `Agent '${this.options.id}' exceeded maximum tool iterations (${DEFAULT_MAX_TOOL_ITERATIONS}).`
        );
    }

    private async executeActionExecutor(
        state: WorkflowData,
        prompt: string,
        executionContext: AgentExecutionContext
    ): Promise<AgentExecutionResult> {
        const actionPolicy = this.options.actionPolicy ?? "auto";
        const proposedActions = this.readActionProposals(state);

        if (proposedActions.length > 0) {
            const approved = this.resolveActionApprovalDecision(state);
            if (approved === undefined) {
                throw new Error(
                    `Action executor '${this.options.id}' requires an approval decision before executing proposed actions.`
                );
            }

            return this.executeApprovedActionPlan(
                state,
                prompt,
                proposedActions,
                actionPolicy,
                approved,
                executionContext
            );
        }

        const request = this.buildRequest(
            state,
            this.buildMessages(prompt),
            this.options.tools,
            "manual"
        );
        const invocation = await this.options.model.generate(request);
        const output = invocation.output ?? invocation.text;
        const plannedActions = toActionProposals(invocation.toolCalls);

        if (plannedActions.length === 0) {
            return this.createAgentExecutionResult(prompt, output, invocation);
        }

        switch (actionPolicy) {
            case "require_approval":
                return this.createAgentExecutionResult(
                    prompt,
                    output,
                    invocation,
                    this.buildPendingActionStatePatch(plannedActions)
                );
            case "dry_run": {
                const actionRecords = this.appendActionRecords(
                    state,
                    plannedActions.map((proposal) =>
                        createActionRecord(
                            this.options.id,
                            proposal,
                            "dry_run",
                            actionPolicy,
                            this.resolveActionRecordOptions()
                        )
                    )
                );

                return this.createAgentExecutionResult(
                    prompt,
                    output,
                    invocation,
                    this.buildResolvedActionStatePatch({
                        actionRecords,
                        rollbackRecords: this.readRollbackRecords(state),
                        dryRunPlan: plannedActions
                    })
                );
            }
            case "confirm_on_error":
            case "auto":
            default:
                return this.executePlannedActions(
                    state,
                    prompt,
                    output,
                    invocation,
                    plannedActions,
                    actionPolicy,
                    false,
                    executionContext
                );
        }
    }

    private async executeApprovedActionPlan(
        state: WorkflowData,
        prompt: string,
        proposedActions: ActionProposal[],
        actionPolicy: ActionPolicy,
        approved: boolean,
        executionContext: AgentExecutionContext
    ): Promise<AgentExecutionResult> {
        const output = state[`${this.options.id}Output`] ?? state[`${this.options.id}_output`] ?? "";

        if (!approved) {
            const actionRecords = this.appendActionRecords(
                state,
                proposedActions.map((proposal) =>
                    createActionRecord(
                        this.options.id,
                        proposal,
                        "rejected",
                        actionPolicy,
                        this.resolveActionRecordOptions()
                    )
                )
            );

            return this.createAgentExecutionResult(
                prompt,
                output,
                createSyntheticInvocation(output, {
                    toolCalls: proposedActions.map(toToolCall)
                }),
                this.buildResolvedActionStatePatch({
                    actionRecords,
                    rollbackRecords: this.readRollbackRecords(state),
                    approved: false,
                    rejected: true
                })
            );
        }

        return this.executePlannedActions(
            state,
            prompt,
            output,
            createSyntheticInvocation(output, {
                toolCalls: proposedActions.map(toToolCall)
            }),
            proposedActions,
            actionPolicy,
            true,
            executionContext
        );
    }

    private async executePlannedActions(
        state: WorkflowData,
        prompt: string,
        output: unknown,
        invocation: ModelInvocationResult,
        plannedActions: ActionProposal[],
        actionPolicy: ActionPolicy,
        approved = false,
        executionContext: AgentExecutionContext
    ): Promise<AgentExecutionResult> {
        const messages = this.buildMessages(prompt);
        const actionRecords: ActionRecord[] = [];
        const toolResults: ToolResult[] = [];

        for (const proposal of plannedActions) {
            const toolDefinition = this.options.tools?.[proposal.tool];

            if (!toolDefinition) {
                const errorMessage = `Unknown tool '${proposal.tool}' for action executor '${this.options.id}'.`;
                const actionRecord = createActionRecord(
                    this.options.id,
                    proposal,
                    "error",
                    actionPolicy,
                    this.resolveActionRecordOptions(),
                    { error: errorMessage }
                );

                actionRecords.push(actionRecord);
                toolResults.push({
                    toolCallId: proposal.toolCallId,
                    name: proposal.tool,
                    output: { error: errorMessage }
                });
                continue;
            }

            try {
                const toolOutput = await toolDefinition.execute(proposal.arguments, {
                    state,
                    messages,
                    agentId: this.options.id,
                    ...(executionContext.stepId ? { stepId: executionContext.stepId } : {})
                });

                actionRecords.push(
                    createActionRecord(
                        this.options.id,
                        proposal,
                        "completed",
                        actionPolicy,
                        this.resolveActionRecordOptions(),
                        toolOutput
                    )
                );
                toolResults.push({
                    toolCallId: proposal.toolCallId,
                    name: proposal.tool,
                    output: toolOutput
                });
            } catch (error) {
                const errorMessage = error instanceof Error ? error.message : String(error);
                const errorOutput = { error: errorMessage };

                actionRecords.push(
                    createActionRecord(
                        this.options.id,
                        proposal,
                        "error",
                        actionPolicy,
                        this.resolveActionRecordOptions(),
                        errorOutput
                    )
                );
                toolResults.push({
                    toolCallId: proposal.toolCallId,
                    name: proposal.tool,
                    output: errorOutput
                });
            }
        }

        const completedInvocation: ModelInvocationResult = {
            ...invocation,
            toolCalls: plannedActions.map(toToolCall),
            toolResults
        };

        const combinedActionRecords = this.appendActionRecords(state, actionRecords);
        const failedActions = actionRecords.filter((record) => record.status === "error");
        const rollbackRecords = await this.executeRollback(
            state,
            messages,
            combinedActionRecords,
            failedActions
        );
        const combinedRollbackRecords = this.appendRollbackRecords(state, rollbackRecords);
        const resolvedStatePatchOptions = {
            actionRecords: combinedActionRecords,
            rollbackRecords: combinedRollbackRecords
        } as {
            actionRecords: ActionRecord[];
            rollbackRecords: RollbackRecord[];
            failedActions?: ActionRecord[];
            recentRollback?: RollbackRecord;
            approved?: boolean;
            rejected?: boolean;
        };

        if (actionPolicy === "confirm_on_error" && failedActions.length > 0) {
            resolvedStatePatchOptions.failedActions = failedActions;

            const recentRollback = rollbackRecords.at(-1);
            if (recentRollback) {
                resolvedStatePatchOptions.recentRollback = recentRollback;
            }
        } else if (approved) {
            resolvedStatePatchOptions.approved = true;
            resolvedStatePatchOptions.rejected = false;
        }

        return this.createAgentExecutionResult(
            prompt,
            output,
            completedInvocation,
            this.buildResolvedActionStatePatch(resolvedStatePatchOptions)
        );
    }

    private async executeRollback(
        state: WorkflowData,
        messages: ModelMessage[],
        actionRecords: ActionRecord[],
        failedActions: ActionRecord[]
    ): Promise<RollbackRecord[]> {
        if (failedActions.length === 0 || this.options.rollbackOnFailure !== true) {
            return [];
        }

        const rollbackAction = this.options.rollbackAction;
        if (typeof rollbackAction !== "string" || rollbackAction.length === 0) {
            return [
                createRollbackRecord(
                    this.options.id,
                    "rollback_not_configured",
                    "error",
                    failedActions,
                    {
                        error: "rollbackOnFailure is enabled but no rollbackAction is configured."
                    }
                )
            ];
        }

        const rollbackTool = this.options.tools?.[rollbackAction];
        if (!rollbackTool) {
            return [
                createRollbackRecord(
                    this.options.id,
                    rollbackAction,
                    "error",
                    failedActions,
                    {
                        error: `Unknown rollback tool '${rollbackAction}' for action executor '${this.options.id}'.`
                    }
                )
            ];
        }

        const rollbackState: WorkflowData = {
            ...state,
            [`${this.options.id}ActionRecords`]: actionRecords,
            [`${this.options.id}_action_records`]: actionRecords,
            [`${this.options.id}FailedActions`]: failedActions,
            [`${this.options.id}_failed_actions`]: failedActions
        };

        try {
            const rollbackResult = await rollbackTool.execute(
                {
                    agentId: this.options.id,
                    failedActions,
                    actionRecords
                },
                {
                    state: rollbackState,
                    messages
                }
            );

            return [
                createRollbackRecord(
                    this.options.id,
                    rollbackAction,
                    "completed",
                    failedActions,
                    rollbackResult
                )
            ];
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);

            return [
                createRollbackRecord(
                    this.options.id,
                    rollbackAction,
                    "error",
                    failedActions,
                    { error: errorMessage }
                )
            ];
        }
    }

    private createAgentExecutionResult(
        prompt: string,
        output: unknown,
        invocation: ModelInvocationResult,
        extraStatePatch: WorkflowData = {}
    ): AgentExecutionResult {
        return {
            agentId: this.options.id,
            behavior: this.behaviorType,
            prompt,
            output,
            invocation,
            statePatch: this.buildStatePatch(output, invocation, extraStatePatch)
        };
    }

    private buildStatePatch(
        output: unknown,
        invocation: ModelInvocationResult,
        extraStatePatch: WorkflowData
    ): WorkflowData {
        const statePatch: WorkflowData = {
            [`${this.options.id}Output`]: output,
            lastAgentId: this.options.id,
            lastOutput: output,
            ...extraStatePatch
        };

        if (invocation.usage) {
            statePatch[`${this.options.id}Usage`] = invocation.usage;
        }

        if (invocation.finishReason) {
            statePatch[`${this.options.id}FinishReason`] = invocation.finishReason;
        }

        return statePatch;
    }

    private buildPendingActionStatePatch(proposedActions: ActionProposal[]): WorkflowData {
        return {
            awaitingActionApproval: true,
            awaiting_action_approval: true,
            pendingActionAgentId: this.options.id,
            pending_action_agent_id: this.options.id,
            [`${this.options.id}ProposedActions`]: proposedActions,
            [`${this.options.id}_proposed_actions`]: proposedActions
        };
    }

    private buildResolvedActionStatePatch(options: {
        actionRecords: ActionRecord[];
        rollbackRecords: RollbackRecord[];
        dryRunPlan?: ActionProposal[];
        approved?: boolean;
        rejected?: boolean;
        failedActions?: ActionRecord[];
        recentRollback?: RollbackRecord;
    }): WorkflowData {
        const lastRollback = options.rollbackRecords.at(-1);
        const statePatch: WorkflowData = {
            awaitingActionApproval: false,
            awaiting_action_approval: false,
            awaitingActionError: false,
            awaiting_action_error: false,
            pendingActionAgentId: undefined,
            pending_action_agent_id: undefined,
            pendingActionErrorAgentId: undefined,
            pending_action_error_agent_id: undefined,
            [`${this.options.id}ProposedActions`]: [],
            [`${this.options.id}_proposed_actions`]: [],
            [`${this.options.id}FailedActions`]: [],
            [`${this.options.id}_failed_actions`]: [],
            [`${this.options.id}ActionErrorDetails`]: undefined,
            [`${this.options.id}_action_error_details`]: undefined,
            [`${this.options.id}RollbackRecords`]: options.rollbackRecords,
            [`${this.options.id}_rollback_records`]: options.rollbackRecords,
            [`${this.options.id}LastRollback`]: lastRollback,
            [`${this.options.id}_last_rollback`]: lastRollback,
            [`${this.options.id}ActionRecords`]: options.actionRecords,
            [`${this.options.id}_action_records`]: options.actionRecords
        };

        if (options.dryRunPlan) {
            statePatch[`${this.options.id}DryRunPlan`] = options.dryRunPlan;
            statePatch[`${this.options.id}_dry_run_plan`] = options.dryRunPlan;
        }

        if (typeof options.approved === "boolean") {
            statePatch[`${this.options.id}ActionApproved`] = options.approved;
            statePatch[`${this.options.id}_action_approved`] = options.approved;
        }

        if (typeof options.rejected === "boolean") {
            statePatch[`${this.options.id}ActionRejected`] = options.rejected;
            statePatch[`${this.options.id}_action_rejected`] = options.rejected;
        }

        if (options.failedActions && options.failedActions.length > 0) {
            statePatch.awaitingActionError = true;
            statePatch.awaiting_action_error = true;
            statePatch.pendingActionErrorAgentId = this.options.id;
            statePatch.pending_action_error_agent_id = this.options.id;
            statePatch[`${this.options.id}FailedActions`] = options.failedActions;
            statePatch[`${this.options.id}_failed_actions`] = options.failedActions;
            statePatch[`${this.options.id}ActionErrorDetails`] = {
                failedActions: options.failedActions,
                actionRecords: options.actionRecords,
                rollback: options.recentRollback
            };
            statePatch[`${this.options.id}_action_error_details`] = {
                failedActions: options.failedActions,
                actionRecords: options.actionRecords,
                rollback: options.recentRollback
            };
        }

        return statePatch;
    }

    private appendActionRecords(state: WorkflowData, actionRecords: ActionRecord[]): ActionRecord[] {
        const existingActionRecords = this.readActionRecords(state);
        return [...existingActionRecords, ...actionRecords];
    }

    private appendRollbackRecords(
        state: WorkflowData,
        rollbackRecords: RollbackRecord[]
    ): RollbackRecord[] {
        const existingRollbackRecords = this.readRollbackRecords(state);
        return [...existingRollbackRecords, ...rollbackRecords];
    }

    private readActionProposals(state: WorkflowData): ActionProposal[] {
        return normalizeActionProposals(
            state[`${this.options.id}ProposedActions`] ?? state[`${this.options.id}_proposed_actions`]
        );
    }

    private readActionRecords(state: WorkflowData): ActionRecord[] {
        return normalizeActionRecords(
            state[`${this.options.id}ActionRecords`] ?? state[`${this.options.id}_action_records`]
        );
    }

    private readRollbackRecords(state: WorkflowData): RollbackRecord[] {
        return normalizeRollbackRecords(
            state[`${this.options.id}RollbackRecords`] ?? state[`${this.options.id}_rollback_records`]
        );
    }

    private resolveActionRecordOptions(): {
        reversible?: boolean;
        rollbackAction?: string;
    } {
        const reversible = this.options.rollbackOnFailure === true;
        const rollbackAction =
            typeof this.options.rollbackAction === "string" && this.options.rollbackAction.length > 0
                ? this.options.rollbackAction
                : undefined;

        return {
            ...(reversible ? { reversible: true } : {}),
            ...(rollbackAction ? { rollbackAction } : {})
        };
    }

    private resolveActionApprovalDecision(state: WorkflowData): boolean | undefined {
        const approved = firstBoolean([
            state[`${this.options.id}ActionApproved`],
            state[`${this.options.id}_action_approved`],
            state.actionApproved,
            state.action_approved
        ]);

        if (approved !== undefined) {
            return approved;
        }

        const rejected = firstBoolean([
            state[`${this.options.id}ActionRejected`],
            state[`${this.options.id}_action_rejected`],
            state.actionRejected,
            state.action_rejected
        ]);

        if (rejected !== undefined) {
            return !rejected;
        }

        return undefined;
    }

    private resolveTools(): Record<string, ToolDefinition> | undefined {
        const entries = new Map<string, ToolDefinition>(Object.entries(this.options.tools ?? {}));

        if (this.behaviorType === "orchestrator" && this.options.collaboration) {
            for (const [toolId, tool] of Object.entries(
                this.options.collaboration.createOrchestratorTools(this)
            )) {
                entries.set(toolId, tool);
            }
        }

        if (entries.size === 0) {
            return undefined;
        }

        return Object.fromEntries(entries);
    }

    private async executeToolCalls(
        state: WorkflowData,
        messages: ModelMessage[],
        tools: Record<string, ToolDefinition>,
        toolCalls: ToolCall[],
        executionContext: AgentExecutionContext
    ): Promise<ToolResult[]> {
        const toolResults: ToolResult[] = [];

        for (const toolCall of toolCalls) {
            const toolDefinition = tools[toolCall.name];
            if (!toolDefinition) {
                toolResults.push({
                    toolCallId: toolCall.id,
                    name: toolCall.name,
                    output: { error: `Unknown tool '${toolCall.name}' for agent '${this.options.id}'.` }
                });
                continue;
            }

            try {
                const output = await toolDefinition.execute(toolCall.input, {
                    state,
                    messages,
                    agentId: this.options.id,
                    ...(executionContext.stepId ? { stepId: executionContext.stepId } : {})
                });

                toolResults.push({
                    toolCallId: toolCall.id,
                    name: toolCall.name,
                    output
                });
            } catch (error) {
                toolResults.push({
                    toolCallId: toolCall.id,
                    name: toolCall.name,
                    output: { error: error instanceof Error ? error.message : String(error) }
                });
            }
        }

        return toolResults;
    }

    private buildMessages(prompt: string): ModelMessage[] {
        return [
            {
                role: "system",
                content: this.buildInstructionMessage()
            },
            {
                role: "user",
                content: prompt
            }
        ];
    }

    private buildPrompt(state: WorkflowData): string {
        if (typeof this.options.prompt === "function") {
            return this.options.prompt(state);
        }

        if (typeof this.options.prompt === "string") {
            return this.options.prompt;
        }

        const task = state.task;
        if (typeof task === "string" && task.trim()) {
            return task;
        }

        return JSON.stringify(state, null, 2);
    }

    private buildInstructionMessage(): string {
        if (this.behaviorType !== "orchestrator" || !this.options.collaboration) {
            return this.options.instructions;
        }

        const activeAgents = this.options.collaboration.listAgentIds();
        const availableArchetypes = this.options.collaboration.listArchetypes();

        return [
            this.options.instructions,
            "",
            "Dynamic collaboration is enabled for this orchestrator.",
            `Active agents: ${activeAgents.length > 0 ? activeAgents.join(", ") : "none"}`,
            `Available archetypes: ${availableArchetypes.length > 0 ? availableArchetypes.join(", ") : "none"}`,
            "Use spawn_agent to create specialists and delegate_task to assign targeted sub-tasks when helpful."
        ].join("\n");
    }
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

function createSyntheticInvocation(
    output: unknown,
    options: {
        toolCalls?: ToolCall[];
        toolResults?: ToolResult[];
    } = {}
): ModelInvocationResult {
    return {
        text: typeof output === "string" ? output : "",
        output,
        toolCalls: options.toolCalls ?? [],
        toolResults: options.toolResults ?? [],
        responseMessages: []
    };
}

function createActionRecord(
    agentId: string,
    proposal: ActionProposal,
    status: ActionRecord["status"],
    policy: ActionPolicy,
    options: {
        reversible?: boolean;
        rollbackAction?: string;
    },
    result?: unknown
): ActionRecord {
    return {
        actionId: proposal.toolCallId,
        agentId,
        tool: proposal.tool,
        arguments: proposal.arguments,
        status,
        policy,
        toolCallId: proposal.toolCallId,
        ...options,
        result
    };
}

function createRollbackRecord(
    agentId: string,
    rollbackAction: string,
    status: RollbackRecord["status"],
    failedActions: ActionRecord[],
    result?: unknown
): RollbackRecord {
    return {
        rollbackId: `${agentId}:rollback:${failedActions[0]?.actionId ?? "unknown"}`,
        agentId,
        rollbackAction,
        status,
        failedActions,
        result
    };
}

function toActionProposals(toolCalls: ToolCall[]): ActionProposal[] {
    return toolCalls.map((toolCall) => ({
        tool: toolCall.name,
        arguments: toolCall.input,
        toolCallId: toolCall.id
    }));
}

function toToolCall(proposal: ActionProposal): ToolCall {
    return {
        id: proposal.toolCallId,
        name: proposal.tool,
        input: proposal.arguments
    };
}

function firstBoolean(values: unknown[]): boolean | undefined {
    for (const value of values) {
        if (typeof value === "boolean") {
            return value;
        }
    }

    return undefined;
}