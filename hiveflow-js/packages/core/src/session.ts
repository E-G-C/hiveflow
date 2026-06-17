import { randomUUID } from "node:crypto";

import type { CheckpointStorage, WorkflowCheckpoint } from "./checkpoint.js";
import type { ActionProposal, ActionRecord, RollbackRecord } from "./agent.js";
import type { Agent } from "./agent.js";
import type { WorkflowDefinition } from "./definition.js";
import type { WorkflowData } from "./types.js";
import type { WorkflowEvent } from "./workflow.js";
import type {
    PendingActionApproval,
    PendingActionError,
    PendingGate,
    PendingHumanInput,
    WorkflowResult
} from "./workflow.js";
import { WorkflowEngine } from "./workflow.js";

export type ApprovalRequestType = "gate" | "human_gate" | "action_approval" | "action_error";

export type WorkflowSessionStatus = "pending" | "running" | "paused" | "completed" | "failed";

export interface ApprovalRequest {
    requestId: string;
    requestType: ApprovalRequestType;
    context: WorkflowData;
    agentId?: string;
    stepId: string;
    createdAt: number;
}

export interface WorkflowSessionOptions {
    workflow: WorkflowEngine;
    agents: Record<string, Agent>;
    initialState?: WorkflowData;
    sessionId?: string;
    checkpointStorage?: CheckpointStorage;
    workflowDefinition?: WorkflowDefinition;
}

export interface LoadWorkflowSessionOptions {
    workflow: WorkflowEngine;
    agents: Record<string, Agent>;
    sessionId: string;
    checkpointStorage: CheckpointStorage;
    checkpointId?: string;
    checkpoint?: WorkflowCheckpoint;
    workflowDefinition?: WorkflowDefinition;
}

export interface WorkflowEventConsumer extends AsyncIterable<WorkflowEvent> {
    close(): void;
}

export class WorkflowSession {
    private readonly workflow: WorkflowEngine;
    private readonly agents: Record<string, Agent>;
    private readonly initialState: WorkflowData | undefined;
    private readonly checkpointStorage: CheckpointStorage | undefined;
    private readonly sessionIdValue: string;
    private workflowDefinition: WorkflowDefinition | undefined;

    private statusValue: WorkflowSessionStatus = "pending";
    private latestResult: WorkflowResult | undefined;
    private pendingRequestsValue: ApprovalRequest[] = [];
    private errorValue: string | undefined;
    private checkpointIdValue: string | undefined;
    private readonly eventChannel = new SessionEventChannel();

    constructor(options: WorkflowSessionOptions) {
        this.workflow = options.workflow;
        this.agents = options.agents;
        this.initialState = options.initialState;
        this.checkpointStorage = options.checkpointStorage;
        this.sessionIdValue = options.sessionId ?? randomUUID();
        this.workflowDefinition = options.workflowDefinition;
    }

    static async load(options: LoadWorkflowSessionOptions): Promise<WorkflowSession> {
        const checkpoint =
            options.checkpoint
            ?? await options.checkpointStorage.load(options.sessionId, options.checkpointId);
        if (!checkpoint) {
            throw new Error(`No checkpoint found for session '${options.sessionId}'.`);
        }

        const sessionOptions = {
            workflow: options.workflow,
            agents: options.agents,
            sessionId: options.sessionId,
            checkpointStorage: options.checkpointStorage
        } as WorkflowSessionOptions;

        const workflowDefinition = options.workflowDefinition ?? checkpoint.workflowDefinition;
        if (workflowDefinition) {
            sessionOptions.workflowDefinition = workflowDefinition;
        }

        const session = new WorkflowSession(sessionOptions);
        session.hydrateFromCheckpoint(checkpoint);
        return session;
    }

    get sessionId(): string {
        return this.sessionIdValue;
    }

    get status(): WorkflowSessionStatus {
        return this.statusValue;
    }

    get result(): WorkflowResult | undefined {
        return this.latestResult;
    }

    get error(): string | undefined {
        return this.errorValue;
    }

    get checkpointId(): string | undefined {
        return this.checkpointIdValue;
    }

    get pendingRequests(): ApprovalRequest[] {
        return [...this.pendingRequestsValue];
    }

    events(): WorkflowEventConsumer {
        return this.eventChannel.subscribe();
    }

    async run(): Promise<WorkflowSession> {
        if (this.statusValue !== "pending") {
            throw new Error(`Cannot run session in '${this.statusValue}' state.`);
        }

        this.statusValue = "running";
        const dispose = this.workflow.onEvent((event) => this.eventChannel.publish(event));
        const request = {
            agents: this.agents,
            sessionId: this.sessionIdValue
        } as {
            agents: Record<string, Agent>;
            initialState?: WorkflowData;
            checkpointStorage?: CheckpointStorage;
            sessionId: string;
            workflowDefinition?: WorkflowDefinition;
        };

        if (this.initialState) {
            request.initialState = this.initialState;
        }

        if (this.checkpointStorage) {
            request.checkpointStorage = this.checkpointStorage;
        }

        if (this.workflowDefinition) {
            request.workflowDefinition = this.workflowDefinition;
        }

        try {
            const result = await this.workflow.execute(request);
            this.applyResult(result);
        } finally {
            dispose();
        }

        return this;
    }

    async resume(responses: WorkflowData): Promise<WorkflowSession> {
        if (!this.latestResult && this.checkpointStorage) {
            const checkpoint = await this.checkpointStorage.load(this.sessionIdValue, this.checkpointIdValue);
            if (checkpoint) {
                this.hydrateFromCheckpoint(checkpoint);
            }
        }

        if (this.statusValue !== "paused" || !this.latestResult) {
            throw new Error(`Cannot resume session in '${this.statusValue}' state.`);
        }

        this.statusValue = "running";
        const dispose = this.workflow.onEvent((event) => this.eventChannel.publish(event));

        try {
            const request = {
                agents: this.agents,
                pausedResult: this.latestResult,
                responses,
                sessionId: this.sessionIdValue
            } as {
                agents: Record<string, Agent>;
                pausedResult: WorkflowResult;
                responses: WorkflowData;
                sessionId: string;
                checkpointStorage?: CheckpointStorage;
                workflowDefinition?: WorkflowDefinition;
            };

            if (this.checkpointStorage) {
                request.checkpointStorage = this.checkpointStorage;
            }

            if (this.workflowDefinition) {
                request.workflowDefinition = this.workflowDefinition;
            }

            const result = await this.workflow.resume(request);

            this.applyResult(result);
        } finally {
            dispose();
        }

        return this;
    }

    cancel(): void {
        if (this.statusValue === "completed" || this.statusValue === "failed") {
            throw new Error(`Cannot cancel session in '${this.statusValue}' state.`);
        }

        this.statusValue = "failed";
        this.errorValue = "Session cancelled";
        this.pendingRequestsValue = [];
        this.eventChannel.close();
    }

    private applyResult(result: WorkflowResult): void {
        this.latestResult = result;
        this.statusValue = result.status;
        this.errorValue = result.error;
        this.pendingRequestsValue = this.extractPendingRequests(result);

        if (result.checkpointId) {
            this.checkpointIdValue = result.checkpointId;
        }

        if (result.status === "completed" || result.status === "failed") {
            this.eventChannel.close();
        }
    }

    private hydrateFromCheckpoint(checkpoint: WorkflowCheckpoint): void {
        this.latestResult = checkpoint.pausedResult;
        this.statusValue = checkpoint.pausedResult.status;
        this.errorValue = checkpoint.pausedResult.error;
        this.pendingRequestsValue = this.extractPendingRequests(checkpoint.pausedResult);
        this.checkpointIdValue = checkpoint.checkpointId;

        if (checkpoint.workflowDefinition) {
            this.workflowDefinition = checkpoint.workflowDefinition;
        }
    }

    private extractPendingRequests(result: WorkflowResult): ApprovalRequest[] {
        if (result.status !== "paused") {
            return [];
        }

        const requests: ApprovalRequest[] = [];
        if (result.pendingGate) {
            requests.push(this.createGateRequest(result.pendingGate));
        }

        if (result.pendingHumanInput) {
            requests.push(this.createHumanGateRequest(result.pendingHumanInput));
        }

        if (result.pendingActionApproval) {
            requests.push(this.createActionApprovalRequest(result.pendingActionApproval));
        }

        if (result.pendingActionError) {
            requests.push(this.createActionErrorRequest(result.pendingActionError));
        }

        return requests;
    }

    private createGateRequest(pendingGate: PendingGate): ApprovalRequest {
        return {
            requestId: randomUUID(),
            requestType: "gate",
            context: {
                gateId: pendingGate.gateId,
                gateDescription: pendingGate.description
            },
            agentId: pendingGate.agentId,
            stepId: pendingGate.stepId,
            createdAt: Date.now()
        };
    }

    private createHumanGateRequest(pendingHumanInput: PendingHumanInput): ApprovalRequest {
        return {
            requestId: randomUUID(),
            requestType: "human_gate",
            context: {
                prompt: pendingHumanInput.prompt
            },
            agentId: pendingHumanInput.agentId,
            stepId: pendingHumanInput.stepId,
            createdAt: Date.now()
        };
    }

    private createActionApprovalRequest(
        pendingActionApproval: PendingActionApproval
    ): ApprovalRequest {
        return {
            requestId: randomUUID(),
            requestType: "action_approval",
            context: {
                policy: pendingActionApproval.policy,
                output: pendingActionApproval.output,
                proposedActions: pendingActionApproval.proposedActions.map(
                    (proposal: ActionProposal) => ({
                        tool: proposal.tool,
                        arguments: proposal.arguments,
                        toolCallId: proposal.toolCallId
                    })
                )
            },
            agentId: pendingActionApproval.agentId,
            stepId: pendingActionApproval.stepId,
            createdAt: Date.now()
        };
    }

    private createActionErrorRequest(
        pendingActionError: PendingActionError
    ): ApprovalRequest {
        return {
            requestId: randomUUID(),
            requestType: "action_error",
            context: {
                policy: pendingActionError.policy,
                output: pendingActionError.output,
                failedActions: pendingActionError.failedActions.map(
                    (record: ActionRecord) => ({
                        actionId: record.actionId,
                        tool: record.tool,
                        arguments: record.arguments,
                        status: record.status,
                        policy: record.policy,
                        toolCallId: record.toolCallId,
                        ...(record.reversible === true ? { reversible: true } : {}),
                        ...(record.rollbackAction ? { rollbackAction: record.rollbackAction } : {}),
                        result: record.result
                    })
                ),
                ...(pendingActionError.rollbackRecord
                    ? {
                        rollbackRecord: this.createRollbackRecordContext(
                            pendingActionError.rollbackRecord
                        )
                    }
                    : {})
            },
            agentId: pendingActionError.agentId,
            stepId: pendingActionError.stepId,
            createdAt: Date.now()
        };
    }

    private createRollbackRecordContext(record: RollbackRecord): WorkflowData {
        return {
            rollbackId: record.rollbackId,
            rollbackAction: record.rollbackAction,
            status: record.status,
            failedActions: record.failedActions.map((actionRecord) => ({
                actionId: actionRecord.actionId,
                tool: actionRecord.tool,
                arguments: actionRecord.arguments,
                status: actionRecord.status,
                policy: actionRecord.policy,
                toolCallId: actionRecord.toolCallId,
                ...(actionRecord.reversible === true ? { reversible: true } : {}),
                ...(actionRecord.rollbackAction ? { rollbackAction: actionRecord.rollbackAction } : {}),
                result: actionRecord.result
            })),
            result: record.result
        };
    }
}

class SessionEventChannel {
    private readonly subscribers = new Set<SessionEventConsumer>();
    private closed = false;

    subscribe(): WorkflowEventConsumer {
        const consumer = new SessionEventConsumer(this);
        this.subscribers.add(consumer);

        if (this.closed) {
            consumer.close();
        }

        return consumer;
    }

    publish(event: WorkflowEvent): void {
        if (this.closed) {
            return;
        }

        for (const consumer of this.subscribers) {
            consumer.push(event);
        }
    }

    close(): void {
        if (this.closed) {
            return;
        }

        this.closed = true;
        for (const consumer of this.subscribers) {
            consumer.close();
        }
        this.subscribers.clear();
    }

    unsubscribe(consumer: SessionEventConsumer): void {
        this.subscribers.delete(consumer);
    }
}

class SessionEventConsumer implements WorkflowEventConsumer, AsyncIterator<WorkflowEvent> {
    private readonly queue: Array<WorkflowEvent | null> = [];
    private readonly waiters: Array<(value: IteratorResult<WorkflowEvent>) => void> = [];
    private isClosed = false;

    constructor(private readonly channel: SessionEventChannel) { }

    [Symbol.asyncIterator](): AsyncIterator<WorkflowEvent> {
        return this;
    }

    next(): Promise<IteratorResult<WorkflowEvent>> {
        const nextItem = this.queue.shift();
        if (nextItem === null) {
            return Promise.resolve({ value: undefined, done: true });
        }

        if (nextItem !== undefined) {
            return Promise.resolve({ value: nextItem, done: false });
        }

        if (this.isClosed) {
            return Promise.resolve({ value: undefined, done: true });
        }

        return new Promise((resolve) => {
            this.waiters.push(resolve);
        });
    }

    close(): void {
        if (this.isClosed) {
            return;
        }

        this.isClosed = true;
        this.channel.unsubscribe(this);

        while (this.waiters.length > 0) {
            const waiter = this.waiters.shift();
            waiter?.({ value: undefined, done: true });
        }

        // Preserve any events a slow consumer has not drained yet; append the
        // done sentinel after them so the iterator yields all buffered events
        // before terminating.
        this.queue.push(null);
    }

    push(event: WorkflowEvent): void {
        if (this.isClosed) {
            return;
        }

        const waiter = this.waiters.shift();
        if (waiter) {
            waiter({ value: event, done: false });
            return;
        }

        this.queue.push(event);
    }
}