import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  Agent,
  ArchetypeLibrary,
  FileCheckpointStorage,
  HiveFlow,
  InMemoryCheckpointStorage,
  WorkflowEngine,
  WorkflowRuntimeCatalog,
  WorkflowSession,
  WorkflowState,
  createMockModel
} from "../src/index.js";
import type { MockModelResponse, WorkflowDefinition } from "../src/index.js";

function createDefinitionRuntimeCatalog(): WorkflowRuntimeCatalog {
  return new WorkflowRuntimeCatalog({
    modelFactories: {
      mock: (definition) => {
        const responses = Array.isArray(definition.options?.responses)
          ? definition.options.responses
          : [];
        const modelId =
          typeof definition.options?.id === "string"
            ? definition.options.id
            : `mock-definition-${definition.kind}`;

        return createMockModel(modelId, (_request, callIndex) =>
          normalizeDefinitionMockResponse(responses[callIndex])
        );
      }
    }
  });
}

function normalizeDefinitionMockResponse(value: unknown): MockModelResponse {
  if (typeof value === "string") {
    return { text: value };
  }

  if (typeof value === "object" && value !== null) {
    return value as MockModelResponse;
  }

  return { text: "" };
}

describe("WorkflowState", () => {
  it("merges state immutably and tracks history", () => {
    const initialState = new WorkflowState({ task: "summarize" });
    const nextState = initialState.merge({ researcherOutput: "notes" });

    expect(initialState.snapshot()).toEqual({ task: "summarize" });
    expect(nextState.snapshot()).toEqual({ task: "summarize", researcherOutput: "notes" });
    expect(nextState.history).toEqual([{ task: "summarize" }]);
  });
});

describe("WorkflowEngine", () => {
  it("executes a sequential workflow and propagates state", async () => {
    const model = createMockModel("mock-sequential", (_request, callIndex) => {
      if (callIndex === 0) {
        return {
          text: "Solar and wind power reduce exposure to fuel price volatility."
        };
      }

      return {
        text: "Renewable energy lowers long-term operating risk and cuts emissions."
      };
    });

    const researcher = new Agent({
      id: "researcher",
      role: "Researcher",
      instructions: "Collect concise research notes for the task.",
      model,
      behavior: "llm_only"
    });

    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write a short synthesis from the prior state.",
      model,
      behavior: "llm_only",
      prompt: (state) =>
        `Task: ${String(state.task ?? "")}\nResearch: ${String(state.researcherOutput ?? "")}`
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "research",
          agent: "researcher",
          type: "sequential",
          next: "write"
        },
        {
          id: "write",
          agent: "writer",
          type: "sequential"
        }
      ]
    });

    const hiveflow = new HiveFlow();
    const result = await hiveflow.run({
      workflow,
      agents: { researcher, writer },
      initialState: { task: "Explain why renewable energy matters." }
    });

    expect(result.status).toBe("completed");
    expect(result.stepResults).toHaveLength(2);
    expect(result.state.researcherOutput).toBe(
      "Solar and wind power reduce exposure to fuel price volatility."
    );
    expect(result.state.writerOutput).toBe(
      "Renewable energy lowers long-term operating risk and cuts emissions."
    );
    expect(result.state.lastAgentId).toBe("writer");
  });

  it("executes parallel fan-out steps and aggregates outputs", async () => {
    const model = createMockModel("mock-parallel", (_request, callIndex) => {
      const outputs = [
        "Auth service findings: token refresh logic needs tighter retry bounds.",
        "Billing service findings: latency spikes trace back to synchronous invoice rendering.",
        "Notifications findings: delivery retries need clearer backoff telemetry."
      ];

      return {
        text: outputs[callIndex] ?? "Unexpected worker output."
      };
    });

    const researcher = new Agent({
      id: "researcher",
      role: "Researcher",
      instructions: "Inspect the assigned work item and return concise findings.",
      model,
      behavior: "llm_only",
      prompt: (state) => `Investigate ${String(state.currentItem ?? "")}`
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "fanout-research",
          agent: "researcher",
          type: "parallel_fan_out"
        }
      ]
    });

    const result = await workflow.execute({
      agents: { researcher },
      initialState: {
        task: "Investigate service risks",
        parallelItems: ["auth", "billing", "notifications"]
      }
    });

    expect(result.status).toBe("completed");
    expect(result.stepResults).toHaveLength(1);
    expect(result.state.researcherOutputs).toEqual([
      "Auth service findings: token refresh logic needs tighter retry bounds.",
      "Billing service findings: latency spikes trace back to synchronous invoice rendering.",
      "Notifications findings: delivery retries need clearer backoff telemetry."
    ]);
    expect(result.state.researcherOutput).toBe(
      [
        "Auth service findings: token refresh logic needs tighter retry bounds.",
        "Billing service findings: latency spikes trace back to synchronous invoice rendering.",
        "Notifications findings: delivery retries need clearer backoff telemetry."
      ].join("\n\n")
    );
    expect(result.state.researcherParallelResults).toMatchObject({
      item_0: {
        currentItem: "auth",
        itemIndex: 0,
        output: "Auth service findings: token refresh logic needs tighter retry bounds."
      },
      item_1: {
        currentItem: "billing",
        itemIndex: 1,
        output:
          "Billing service findings: latency spikes trace back to synchronous invoice rendering."
      },
      item_2: {
        currentItem: "notifications",
        itemIndex: 2,
        output: "Notifications findings: delivery retries need clearer backoff telemetry."
      }
    });
    expect(result.state.lastAgentId).toBe("researcher");
  });

  it("routes conditional steps back through revision until accepted", async () => {
    const model = createMockModel("mock-conditional", (_request, callIndex) => {
      switch (callIndex) {
        case 0:
          return {
            text: "Draft v1: renewable energy reduces emissions and long-term operating costs."
          };
        case 1:
          return {
            text: "Needs revision. Add evidence about resilience and reliability."
          };
        case 2:
          return {
            text: "Draft v2: renewable energy reduces emissions, lowers long-term costs, and improves grid resilience."
          };
        case 3:
          return {
            text: "Approved. Meets criteria for clarity and coverage."
          };
        default:
          return {
            text: "Unexpected conditional output."
          };
      }
    });

    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write or revise the draft using the latest reviewer feedback.",
      model,
      behavior: "llm_only",
      prompt: (state) =>
        `Task: ${String(state.task ?? "")}\nFeedback: ${String(state.reviewerOutput ?? "none")}`
    });

    const reviewer = new Agent({
      id: "reviewer",
      role: "Reviewer",
      instructions: "Review the draft and explicitly approve or request revision.",
      model,
      behavior: "llm_only",
      prompt: (state) => `Review this draft: ${String(state.writerOutput ?? "")}`
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "draft",
          agent: "writer",
          type: "sequential",
          next: "review"
        },
        {
          id: "review",
          agent: "reviewer",
          type: "conditional",
          nextOnReject: "draft",
          maxIterations: 3
        }
      ]
    });

    const result = await workflow.execute({
      agents: { writer, reviewer },
      initialState: { task: "Explain why renewable energy matters." }
    });

    expect(result.status).toBe("completed");
    expect(result.stepResults.map((step) => step.stepId)).toEqual([
      "draft",
      "review",
      "draft",
      "review"
    ]);
    expect(result.state.writerOutput).toBe(
      "Draft v2: renewable energy reduces emissions, lowers long-term costs, and improves grid resilience."
    );
    expect(result.state.reviewerOutput).toBe(
      "Approved. Meets criteria for clarity and coverage."
    );
  });

  it("fails conditional steps that exceed max iterations", async () => {
    const model = createMockModel("mock-conditional-limit", (_request, callIndex) => {
      switch (callIndex) {
        case 0:
          return {
            text: "Draft v1: renewable energy reduces emissions."
          };
        case 1:
          return {
            text: "Needs revision. Add evidence."
          };
        case 2:
          return {
            text: "Draft v2: renewable energy reduces emissions and lowers fuel risk."
          };
        case 3:
          return {
            text: "Needs revision. Still insufficient."
          };
        case 4:
          return {
            text: "Draft v3: renewable energy reduces emissions, lowers fuel risk, and improves resilience."
          };
        case 5:
          return {
            text: "Needs revision. Fails acceptance criteria."
          };
        default:
          return {
            text: "Unexpected max-iteration output."
          };
      }
    });

    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write or revise the draft using the latest reviewer feedback.",
      model,
      behavior: "llm_only"
    });

    const reviewer = new Agent({
      id: "reviewer",
      role: "Reviewer",
      instructions: "Review the draft and decide whether it passes.",
      model,
      behavior: "llm_only",
      prompt: (state) => `Review this draft: ${String(state.writerOutput ?? "")}`
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "draft",
          agent: "writer",
          type: "sequential",
          next: "review"
        },
        {
          id: "review",
          agent: "reviewer",
          type: "conditional",
          nextOnReject: "draft",
          maxIterations: 2
        }
      ]
    });

    const result = await workflow.execute({
      agents: { writer, reviewer },
      initialState: { task: "Explain why renewable energy matters." }
    });

    expect(result.status).toBe("failed");
    expect(result.error).toContain("exceeded maximum iterations (2)");
  });

  it("supports orchestrator collaboration with runtime spawning and delegation", async () => {
    const runtimeCatalog = new WorkflowRuntimeCatalog({
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns(),
      modelFactories: {
        mock: (definition) => {
          const responses = Array.isArray(definition.options?.responses)
            ? definition.options.responses
            : [];
          const modelId =
            typeof definition.options?.id === "string"
              ? definition.options.id
              : "mock-collaboration";

          return createMockModel(modelId, (_request, callIndex) =>
            normalizeDefinitionMockResponse(responses[callIndex])
          );
        }
      }
    });
    const definition: WorkflowDefinition = {
      id: "dynamic-collaboration",
      collaboration: {
        enabled: true,
        maxDelegationDepth: 3,
        maxSpawnedAgents: 3,
        delegationTimeoutSeconds: 30,
        budgetPolicy: "inherit_parent"
      },
      agents: [
        {
          id: "planner",
          role: "Planner",
          instructions: "Break work into sub-tasks, spawn specialists, and delegate as needed.",
          behavior: "orchestrator",
          model: {
            kind: "mock",
            options: {
              id: "mock-collaboration-planner",
              responses: [
                {
                  toolCalls: [
                    {
                      id: "spawn-1",
                      name: "spawn_agent",
                      input: { archetype: "writer" }
                    }
                  ]
                },
                {
                  toolCalls: [
                    {
                      id: "delegate-1",
                      name: "delegate_task",
                      input: {
                        task: "Write one sentence explaining why renewable energy matters.",
                        delegate_to: "spawned_writer_1"
                      }
                    }
                  ]
                },
                {
                  text: "Renewable energy cuts emissions and lowers long-term fuel risk."
                },
                {
                  text: "Delegated work complete."
                }
              ]
            }
          }
        }
      ],
      steps: [
        {
          id: "plan",
          agent: "planner",
          type: "sequential"
        }
      ]
    };
    const runtime = runtimeCatalog.build(definition);
    const events: Array<{ type: string; agentId?: string; spawnedBy?: string; delegateTo?: string }> = [];

    runtime.workflow.onEvent((event) => {
      events.push(event);
    });

    const result = await runtime.workflow.execute({
      agents: runtime.agents,
      initialState: {
        task: "Explain why renewable energy matters."
      }
    });

    expect(result.status).toBe("completed");
    expect(result.state.plannerOutput).toBe("Delegated work complete.");
    expect(events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "agent_spawned",
          agentId: "spawned_writer_1",
          spawnedBy: "planner"
        }),
        expect.objectContaining({
          type: "delegation_completed",
          agentId: "planner",
          delegateTo: "spawned_writer_1"
        })
      ])
    );
  });

  it("pauses on gated steps before agent execution", async () => {
    const checkpointStorage = new InMemoryCheckpointStorage();
    const events = [] as Array<{ type: string; checkpointId?: string; sessionId?: string }>;
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "approve-deploy",
          agent: "deployer",
          type: "gated",
          gate: "deploy_approval",
          gateDescription: "Approve deployment to staging.",
          next: "deploy"
        },
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential"
        }
      ]
    });

    workflow.onEvent((event) => {
      events.push(event);
    });

    const result = await workflow.execute({
      agents: {},
      initialState: { task: "Deploy the release candidate." },
      sessionId: "session-gated-checkpoint",
      checkpointStorage
    });

    const checkpoint = await checkpointStorage.load("session-gated-checkpoint");

    expect(result.status).toBe("paused");
    expect(result.checkpointId).toBeTruthy();
    expect(result.stepResults).toEqual([
      {
        stepId: "approve-deploy",
        agentId: "deployer",
        type: "gated",
        status: "paused",
        state: {
          task: "Deploy the release candidate.",
          awaitingGateApproval: true,
          awaiting_gate_approval: true,
          pendingGateId: "deploy_approval",
          pending_gate_id: "deploy_approval",
          pendingGateDescription: "Approve deployment to staging.",
          pending_gate_description: "Approve deployment to staging.",
          pendingGateStepId: "approve-deploy",
          pendingGateAgentId: "deployer"
        }
      }
    ]);
    expect(checkpoint?.pausedResult).toEqual(result);
    expect(result.pendingGate).toEqual({
      stepId: "approve-deploy",
      agentId: "deployer",
      gateId: "deploy_approval",
      description: "Approve deployment to staging."
    });
    expect(result.pauseContext).toEqual({
      stepId: "approve-deploy",
      stepIndex: 0,
      agentId: "deployer",
      reason: "gated",
      iterationCounts: {}
    });
    expect(events.at(-1)).toMatchObject({
      type: "checkpoint_saved",
      sessionId: "session-gated-checkpoint",
      checkpointId: result.checkpointId
    });
    expect(result.state.deployerOutput).toBeUndefined();
  });

  it("pauses on human-gate steps when no human input is present", async () => {
    const model = createMockModel("mock-human-gate", () => ({ text: "unused" }));
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model,
      behavior: "human_gate"
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate"
        }
      ]
    });

    const result = await workflow.execute({
      agents: { approver },
      initialState: { task: "Approve the release candidate." }
    });

    expect(result.status).toBe("paused");
    expect(result.pendingHumanInput).toEqual({
      stepId: "request-approval",
      agentId: "approver",
      prompt: "Agent 'Human Approver' requires your input."
    });
    expect(result.pauseContext).toEqual({
      stepId: "request-approval",
      stepIndex: 0,
      agentId: "approver",
      reason: "human_gate",
      iterationCounts: {}
    });
    expect(result.stepResults).toEqual([
      {
        stepId: "request-approval",
        agentId: "approver",
        type: "human_gate",
        status: "paused",
        state: {
          task: "Approve the release candidate.",
          awaitingHumanInput: true,
          awaiting_human_input: true,
          humanPrompt: "Agent 'Human Approver' requires your input.",
          human_prompt: "Agent 'Human Approver' requires your input.",
          pendingHumanAgentId: "approver",
          pending_human_agent_id: "approver",
          lastAgentId: "approver"
        }
      }
    ]);
  });

  it("completes human-gate steps when input is already present", async () => {
    const model = createMockModel("mock-human-gate-accepted", () => ({ text: "unused" }));
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model,
      behavior: "human_gate"
    });
    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write the post-approval release note.",
      model: createMockModel("mock-human-gate-writer", () => ({
        text: "Release approved. Publishing the release note."
      })),
      behavior: "llm_only"
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate",
          next: "publish"
        },
        {
          id: "publish",
          agent: "writer",
          type: "sequential"
        }
      ]
    });

    const result = await workflow.execute({
      agents: { approver, writer },
      initialState: {
        task: "Approve and publish the release note.",
        humanInput: "approved"
      }
    });

    expect(result.status).toBe("completed");
    expect(result.pendingHumanInput).toBeUndefined();
    expect(result.state.approverOutput).toBe("approved");
    expect(result.state.approverApproved).toBe(true);
    expect(result.state.writerOutput).toBe("Release approved. Publishing the release note.");
  });

  it("resumes gated workflows in memory after approval", async () => {
    const publisher = new Agent({
      id: "publisher",
      role: "Publisher",
      instructions: "Publish the approved release note.",
      model: createMockModel("mock-gated-resume-publisher", () => ({
        text: "Release note published after approval."
      })),
      behavior: "llm_only"
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "approve-release",
          agent: "deployer",
          type: "gated",
          gate: "deploy_approval",
          gateDescription: "Approve the release.",
          next: "publish"
        },
        {
          id: "publish",
          agent: "publisher",
          type: "sequential"
        }
      ]
    });

    const paused = await workflow.execute({
      agents: { publisher },
      initialState: { task: "Approve and publish the release note." }
    });
    const resumed = await workflow.resume({
      agents: { publisher },
      pausedResult: paused,
      responses: { deploy_approval: true }
    });

    expect(paused.status).toBe("paused");
    expect(resumed.status).toBe("completed");
    expect(resumed.pauseContext).toBeUndefined();
    expect(resumed.pendingGate).toBeUndefined();
    expect(resumed.state.awaitingGateApproval).toBe(false);
    expect(resumed.state.deploy_approval).toBe(true);
    expect(resumed.state.writerOutput).toBeUndefined();
    expect(resumed.state.publisherOutput).toBe("Release note published after approval.");
    expect(resumed.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "approve-release:paused",
      "publish:completed"
    ]);
  });

  it("resumes human-gate workflows in memory through the HiveFlow facade", async () => {
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model: createMockModel("mock-human-gate-resume-approver", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write the approved release note.",
      model: createMockModel("mock-human-gate-resume-writer", (_request) => ({
        text: "Approved release note published."
      })),
      behavior: "llm_only",
      prompt: (state) => `Approval: ${String(state.approverOutput ?? "pending")}`
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate",
          next: "publish"
        },
        {
          id: "publish",
          agent: "writer",
          type: "sequential"
        }
      ]
    });
    const hiveflow = new HiveFlow();

    const paused = await hiveflow.run({
      workflow,
      agents: { approver, writer },
      initialState: { task: "Approve and publish the release note." }
    });
    const resumed = await hiveflow.resume({
      workflow,
      agents: { approver, writer },
      pausedResult: paused,
      responses: { humanInput: "approved" }
    });

    expect(paused.status).toBe("paused");
    expect(resumed.status).toBe("completed");
    expect(resumed.pendingHumanInput).toBeUndefined();
    expect(resumed.state.awaitingHumanInput).toBe(false);
    expect(resumed.state.approverOutput).toBe("approved");
    expect(resumed.state.writerOutput).toBe("Approved release note published.");
    expect(resumed.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "request-approval:paused",
      "publish:completed"
    ]);
  });

  it("executes action_executor tools immediately under the auto policy", async () => {
    const executedActions: Array<{ environment: string; version: string }> = [];
    const deployer = new Agent({
      id: "deployer",
      role: "Deployer",
      instructions: "Choose and execute the deployment action.",
      model: createMockModel("mock-action-auto", () => ({
        text: "Deploy the current build to staging.",
        toolCalls: [
          {
            id: "call-deploy-staging",
            name: "deploy_release",
            input: {
              environment: "staging",
              version: "2026.03.06"
            }
          }
        ]
      })),
      behavior: "action_executor",
      actionPolicy: "auto",
      tools: {
        deploy_release: {
          description: "Deploy a release to the requested environment.",
          inputSchema: z.object({
            environment: z.string(),
            version: z.string()
          }),
          execute: async (input) => {
            const typedInput = input as { environment: string; version: string };
            executedActions.push(typedInput);
            return {
              ok: true,
              deploymentId: "dep-123",
              environment: typedInput.environment,
              version: typedInput.version
            };
          }
        }
      }
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential"
        }
      ]
    });

    const result = await workflow.execute({
      agents: { deployer },
      initialState: { task: "Deploy the release candidate to staging." }
    });

    expect(result.status).toBe("completed");
    expect(executedActions).toEqual([
      {
        environment: "staging",
        version: "2026.03.06"
      }
    ]);
    expect(result.state.deployerActionRecords).toEqual([
      {
        actionId: "call-deploy-staging",
        agentId: "deployer",
        tool: "deploy_release",
        arguments: {
          environment: "staging",
          version: "2026.03.06"
        },
        status: "completed",
        policy: "auto",
        toolCallId: "call-deploy-staging",
        result: {
          ok: true,
          deploymentId: "dep-123",
          environment: "staging",
          version: "2026.03.06"
        }
      }
    ]);
    expect(result.state.deployerOutput).toBe("Deploy the current build to staging.");
    expect(result.state.awaitingActionApproval).toBe(false);
  });

  it("rolls back failed auto action_executor steps when rollback_on_failure is enabled", async () => {
    const executedActions: string[] = [];
    const rollbackPayloads: Array<Record<string, unknown>> = [];

    const deployer = new Agent({
      id: "deployer",
      role: "Deployer",
      instructions: "Execute the rollout automatically and rollback if a step fails.",
      model: createMockModel("mock-action-auto-rollback", () => ({
        text: "Deploy the release and notify operators.",
        toolCalls: [
          {
            id: "call-auto-deploy",
            name: "deploy_release",
            input: {
              environment: "staging",
              version: "2026.03.06"
            }
          },
          {
            id: "call-auto-notify",
            name: "notify_release",
            input: {
              channel: "ops",
              version: "2026.03.06"
            }
          }
        ]
      })),
      behavior: "action_executor",
      actionPolicy: "auto",
      rollbackOnFailure: true,
      rollbackAction: "rollback_deploy",
      tools: {
        deploy_release: {
          description: "Deploy a release to the requested environment.",
          inputSchema: z.object({
            environment: z.string(),
            version: z.string()
          }),
          execute: async (input) => {
            const typedInput = input as { environment: string; version: string };
            executedActions.push(`deploy:${typedInput.environment}:${typedInput.version}`);
            return {
              ok: true,
              deploymentId: "dep-auto-rollback",
              environment: typedInput.environment,
              version: typedInput.version
            };
          }
        },
        notify_release: {
          description: "Send the deployment notification.",
          inputSchema: z.object({
            channel: z.string(),
            version: z.string()
          }),
          execute: async (input) => {
            const typedInput = input as { channel: string; version: string };
            executedActions.push(`notify:${typedInput.channel}:${typedInput.version}`);
            throw new Error("Notification service is unavailable.");
          }
        },
        rollback_deploy: {
          description: "Rollback the previously deployed release.",
          inputSchema: z.object({
            agentId: z.string(),
            failedActions: z.array(z.unknown()),
            actionRecords: z.array(z.unknown())
          }),
          execute: async (input) => {
            rollbackPayloads.push(input as Record<string, unknown>);
            executedActions.push("rollback:deploy_release");
            return {
              ok: true,
              restoredDeploymentId: "dep-auto-rollback"
            };
          }
        }
      }
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential"
        }
      ]
    });

    const result = await workflow.execute({
      agents: { deployer },
      initialState: { task: "Deploy the release candidate and notify operators." }
    });

    expect(result.status).toBe("completed");
    expect(executedActions).toEqual([
      "deploy:staging:2026.03.06",
      "notify:ops:2026.03.06",
      "rollback:deploy_release"
    ]);
    expect(rollbackPayloads[0]).toMatchObject({
      agentId: "deployer",
      failedActions: [
        {
          actionId: "call-auto-notify"
        }
      ]
    });
    expect((rollbackPayloads[0]?.actionRecords as unknown[] | undefined)?.length).toBe(2);
    expect(result.state.deployerActionRecords).toEqual([
      {
        actionId: "call-auto-deploy",
        agentId: "deployer",
        tool: "deploy_release",
        arguments: {
          environment: "staging",
          version: "2026.03.06"
        },
        status: "completed",
        policy: "auto",
        toolCallId: "call-auto-deploy",
        reversible: true,
        rollbackAction: "rollback_deploy",
        result: {
          ok: true,
          deploymentId: "dep-auto-rollback",
          environment: "staging",
          version: "2026.03.06"
        }
      },
      {
        actionId: "call-auto-notify",
        agentId: "deployer",
        tool: "notify_release",
        arguments: {
          channel: "ops",
          version: "2026.03.06"
        },
        status: "error",
        policy: "auto",
        toolCallId: "call-auto-notify",
        reversible: true,
        rollbackAction: "rollback_deploy",
        result: {
          error: "Notification service is unavailable."
        }
      }
    ]);
    expect(result.state.deployerRollbackRecords).toEqual([
      {
        rollbackId: "deployer:rollback:call-auto-notify",
        agentId: "deployer",
        rollbackAction: "rollback_deploy",
        status: "completed",
        failedActions: [
          {
            actionId: "call-auto-notify",
            agentId: "deployer",
            tool: "notify_release",
            arguments: {
              channel: "ops",
              version: "2026.03.06"
            },
            status: "error",
            policy: "auto",
            toolCallId: "call-auto-notify",
            reversible: true,
            rollbackAction: "rollback_deploy",
            result: {
              error: "Notification service is unavailable."
            }
          }
        ],
        result: {
          ok: true,
          restoredDeploymentId: "dep-auto-rollback"
        }
      }
    ]);
  });

  it("pauses confirm_on_error action_executor steps after a tool failure and resumes to the next step", async () => {
    const executedActions: string[] = [];
    let plannerCalls = 0;

    const deployer = new Agent({
      id: "deployer",
      role: "Deployer",
      instructions: "Execute the rollout and escalate only if something fails.",
      model: createMockModel("mock-action-confirm-on-error", () => {
        plannerCalls += 1;
        return {
          text: "Deploy the release and post a deployment notification.",
          toolCalls: [
            {
              id: "call-confirm-deploy",
              name: "deploy_release",
              input: {
                environment: "staging",
                version: "2026.03.06"
              }
            },
            {
              id: "call-confirm-notify",
              name: "notify_release",
              input: {
                channel: "ops",
                version: "2026.03.06"
              }
            }
          ]
        };
      }),
      behavior: "action_executor",
      actionPolicy: "confirm_on_error",
      rollbackOnFailure: true,
      rollbackAction: "rollback_deploy",
      tools: {
        deploy_release: {
          description: "Deploy a release to the requested environment.",
          inputSchema: z.object({
            environment: z.string(),
            version: z.string()
          }),
          execute: async (input) => {
            const typedInput = input as { environment: string; version: string };
            executedActions.push(`deploy:${typedInput.environment}:${typedInput.version}`);
            return {
              ok: true,
              deploymentId: "dep-confirm",
              environment: typedInput.environment,
              version: typedInput.version
            };
          }
        },
        notify_release: {
          description: "Send the deployment notification.",
          inputSchema: z.object({
            channel: z.string(),
            version: z.string()
          }),
          execute: async (input) => {
            const typedInput = input as { channel: string; version: string };
            executedActions.push(`notify:${typedInput.channel}:${typedInput.version}`);
            throw new Error("Notification service is unavailable.");
          }
        },
        rollback_deploy: {
          description: "Rollback the previously deployed release.",
          inputSchema: z.object({
            agentId: z.string(),
            failedActions: z.array(z.unknown()),
            actionRecords: z.array(z.unknown())
          }),
          execute: async () => {
            executedActions.push("rollback:deploy_release");
            return {
              ok: true,
              restoredDeploymentId: "dep-confirm"
            };
          }
        }
      }
    });
    const announcer = new Agent({
      id: "announcer",
      role: "Announcer",
      instructions: "Summarize the deployment state after the escalation is acknowledged.",
      model: createMockModel("mock-action-confirm-on-error-writer", () => ({
        text: "Escalation acknowledged. Deployment status recorded for follow-up."
      })),
      behavior: "llm_only"
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential",
          next: "announce"
        },
        {
          id: "announce",
          agent: "announcer",
          type: "sequential"
        }
      ]
    });

    const paused = await workflow.execute({
      agents: { deployer, announcer },
      initialState: { task: "Deploy the release candidate and notify operators." }
    });

    expect(paused.status).toBe("paused");
    expect(plannerCalls).toBe(1);
    expect(paused.pendingActionError).toEqual({
      stepId: "deploy",
      agentId: "deployer",
      failedActions: [
        {
          actionId: "call-confirm-notify",
          agentId: "deployer",
          tool: "notify_release",
          arguments: {
            channel: "ops",
            version: "2026.03.06"
          },
          status: "error",
          policy: "confirm_on_error",
          toolCallId: "call-confirm-notify",
          reversible: true,
          rollbackAction: "rollback_deploy",
          result: {
            error: "Notification service is unavailable."
          }
        }
      ],
      policy: "confirm_on_error",
      output: "Deploy the release and post a deployment notification.",
      rollbackRecord: {
        rollbackId: "deployer:rollback:call-confirm-notify",
        agentId: "deployer",
        rollbackAction: "rollback_deploy",
        status: "completed",
        failedActions: [
          {
            actionId: "call-confirm-notify",
            agentId: "deployer",
            tool: "notify_release",
            arguments: {
              channel: "ops",
              version: "2026.03.06"
            },
            status: "error",
            policy: "confirm_on_error",
            toolCallId: "call-confirm-notify",
            reversible: true,
            rollbackAction: "rollback_deploy",
            result: {
              error: "Notification service is unavailable."
            }
          }
        ],
        result: {
          ok: true,
          restoredDeploymentId: "dep-confirm"
        }
      }
    });
    expect(paused.state.deployerActionRecords).toEqual([
      {
        actionId: "call-confirm-deploy",
        agentId: "deployer",
        tool: "deploy_release",
        arguments: {
          environment: "staging",
          version: "2026.03.06"
        },
        status: "completed",
        policy: "confirm_on_error",
        toolCallId: "call-confirm-deploy",
        reversible: true,
        rollbackAction: "rollback_deploy",
        result: {
          ok: true,
          deploymentId: "dep-confirm",
          environment: "staging",
          version: "2026.03.06"
        }
      },
      {
        actionId: "call-confirm-notify",
        agentId: "deployer",
        tool: "notify_release",
        arguments: {
          channel: "ops",
          version: "2026.03.06"
        },
        status: "error",
        policy: "confirm_on_error",
        toolCallId: "call-confirm-notify",
        reversible: true,
        rollbackAction: "rollback_deploy",
        result: {
          error: "Notification service is unavailable."
        }
      }
    ]);
    expect(paused.state.deployerRollbackRecords).toEqual([
      {
        rollbackId: "deployer:rollback:call-confirm-notify",
        agentId: "deployer",
        rollbackAction: "rollback_deploy",
        status: "completed",
        failedActions: [
          {
            actionId: "call-confirm-notify",
            agentId: "deployer",
            tool: "notify_release",
            arguments: {
              channel: "ops",
              version: "2026.03.06"
            },
            status: "error",
            policy: "confirm_on_error",
            toolCallId: "call-confirm-notify",
            reversible: true,
            rollbackAction: "rollback_deploy",
            result: {
              error: "Notification service is unavailable."
            }
          }
        ],
        result: {
          ok: true,
          restoredDeploymentId: "dep-confirm"
        }
      }
    ]);
    expect(paused.state.awaitingActionError).toBe(true);
    expect(executedActions).toEqual([
      "deploy:staging:2026.03.06",
      "notify:ops:2026.03.06",
      "rollback:deploy_release"
    ]);

    const resumed = await workflow.resume({
      agents: { deployer, announcer },
      pausedResult: paused,
      responses: { deployerActionErrorAcknowledged: true }
    });

    expect(resumed.status).toBe("completed");
    expect(plannerCalls).toBe(1);
    expect(resumed.state.deployerActionErrorAcknowledged).toBe(true);
    expect(resumed.state.announcerOutput).toBe(
      "Escalation acknowledged. Deployment status recorded for follow-up."
    );
    expect(resumed.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "deploy:paused",
      "announce:completed"
    ]);
  });

  it("pauses action_executor steps for approval and resumes by re-entering the same step", async () => {
    const executedActions: Array<{ environment: string; version: string }> = [];
    let plannerCalls = 0;

    const deployer = new Agent({
      id: "deployer",
      role: "Deployer",
      instructions: "Plan the deployment action before executing it.",
      model: createMockModel("mock-action-approval", () => {
        plannerCalls += 1;
        return {
          text: "Deploy the approved release to staging.",
          toolCalls: [
            {
              id: "call-approved-deploy",
              name: "deploy_release",
              input: {
                environment: "staging",
                version: "2026.03.06"
              }
            }
          ]
        };
      }),
      behavior: "action_executor",
      actionPolicy: "require_approval",
      tools: {
        deploy_release: {
          description: "Deploy a release to the requested environment.",
          inputSchema: z.object({
            environment: z.string(),
            version: z.string()
          }),
          execute: async (input) => {
            const typedInput = input as { environment: string; version: string };
            executedActions.push(typedInput);
            return {
              ok: true,
              deploymentId: "dep-approved",
              environment: typedInput.environment,
              version: typedInput.version
            };
          }
        }
      }
    });
    const announcer = new Agent({
      id: "announcer",
      role: "Announcer",
      instructions: "Publish the deployment outcome.",
      model: createMockModel("mock-action-approval-writer", () => ({
        text: "Deployment approved, executed, and announced."
      })),
      behavior: "llm_only"
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential",
          next: "announce"
        },
        {
          id: "announce",
          agent: "announcer",
          type: "sequential"
        }
      ]
    });

    const paused = await workflow.execute({
      agents: { deployer, announcer },
      initialState: { task: "Deploy the approved release to staging." }
    });

    expect(paused.status).toBe("paused");
    expect(paused.pendingActionApproval).toEqual({
      stepId: "deploy",
      agentId: "deployer",
      proposedActions: [
        {
          tool: "deploy_release",
          arguments: {
            environment: "staging",
            version: "2026.03.06"
          },
          toolCallId: "call-approved-deploy"
        }
      ],
      policy: "require_approval",
      output: "Deploy the approved release to staging."
    });

    const resumed = await workflow.resume({
      agents: { deployer, announcer },
      pausedResult: paused,
      responses: { deployerActionApproved: true }
    });

    expect(resumed.status).toBe("completed");
    expect(plannerCalls).toBe(1);
    expect(executedActions).toEqual([
      {
        environment: "staging",
        version: "2026.03.06"
      }
    ]);
    expect(resumed.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "deploy:paused",
      "deploy:completed",
      "announce:completed"
    ]);
    expect(resumed.state.deployerActionApproved).toBe(true);
    expect(resumed.state.deployerActionRecords).toEqual([
      {
        actionId: "call-approved-deploy",
        agentId: "deployer",
        tool: "deploy_release",
        arguments: {
          environment: "staging",
          version: "2026.03.06"
        },
        status: "completed",
        policy: "require_approval",
        toolCallId: "call-approved-deploy",
        result: {
          ok: true,
          deploymentId: "dep-approved",
          environment: "staging",
          version: "2026.03.06"
        }
      }
    ]);
    expect(resumed.state.announcerOutput).toBe("Deployment approved, executed, and announced.");
  });

  it("executes registered sub_workflow steps with input and output mapping", async () => {
    const researchModel = createMockModel("mock-subworkflow-research", () => ({
      text: "Renewable energy improves resilience by reducing exposure to fuel supply shocks."
    }));
    const reviewerModel = createMockModel("mock-subworkflow-review", () => ({
      text: "Approved. Research coverage is sufficient for publication."
    }));
    const publisherModel = createMockModel("mock-subworkflow-publisher", () => ({
      text: "Published the research summary using the nested workflow findings."
    }));

    const researcher = new Agent({
      id: "researcher",
      role: "Researcher",
      instructions: "Produce concise research findings for the task.",
      model: researchModel,
      behavior: "llm_only"
    });
    const reviewer = new Agent({
      id: "reviewer",
      role: "Reviewer",
      instructions: "Review the nested workflow findings.",
      model: reviewerModel,
      behavior: "llm_only",
      prompt: (state) => `Review findings: ${String(state.researcherOutput ?? "")}`
    });
    const publisher = new Agent({
      id: "publisher",
      role: "Publisher",
      instructions: "Publish the parent workflow output.",
      model: publisherModel,
      behavior: "llm_only",
      prompt: (state) =>
        `Findings: ${String(state.findings ?? "")}
Review: ${String(state.reviewDecision ?? "")}`
    });

    const nestedWorkflow = new WorkflowEngine({
      steps: [
        {
          id: "research",
          agent: "researcher",
          type: "sequential",
          next: "review"
        },
        {
          id: "review",
          agent: "reviewer",
          type: "sequential"
        }
      ]
    });
    const workflow = new WorkflowEngine({
      subWorkflows: {
        deep_research: {
          workflow: nestedWorkflow,
          agents: { researcher, reviewer }
        }
      },
      steps: [
        {
          id: "research-phase",
          agent: "research_team",
          type: "sub_workflow",
          team: "deep_research",
          inputMapping: { task: "researchQuestion" },
          outputMapping: {
            findings: "researcherOutput",
            reviewDecision: "reviewerOutput"
          },
          next: "publish"
        },
        {
          id: "publish",
          agent: "publisher",
          type: "sequential"
        }
      ]
    });

    const result = await workflow.execute({
      agents: { publisher },
      initialState: { researchQuestion: "Explain why renewable energy improves resilience." }
    });

    expect(result.status).toBe("completed");
    expect(result.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "research-phase:completed",
      "publish:completed"
    ]);
    expect(result.state.findings).toBe(
      "Renewable energy improves resilience by reducing exposure to fuel supply shocks."
    );
    expect(result.state.reviewDecision).toBe(
      "Approved. Research coverage is sufficient for publication."
    );
    expect(result.state.publisherOutput).toBe(
      "Published the research summary using the nested workflow findings."
    );
  });

  it("merges the full nested state when sub_workflow output mapping is omitted", async () => {
    const analyzer = new Agent({
      id: "analyzer",
      role: "Analyzer",
      instructions: "Analyze the incoming task.",
      model: createMockModel("mock-subworkflow-merge", () => ({
        text: "Nested workflow analysis complete."
      })),
      behavior: "llm_only"
    });
    const nestedWorkflow = new WorkflowEngine({
      steps: [
        {
          id: "analyze",
          agent: "analyzer",
          type: "sequential"
        }
      ]
    });
    const workflow = new WorkflowEngine({
      subWorkflows: {
        analysis_team: {
          workflow: nestedWorkflow,
          agents: { analyzer }
        }
      },
      steps: [
        {
          id: "analysis",
          agent: "analysis_team",
          type: "sub_workflow",
          team: "analysis_team"
        }
      ]
    });

    const result = await workflow.execute({
      agents: {},
      initialState: { task: "Analyze the release blockers." }
    });

    expect(result.status).toBe("completed");
    expect(result.state.task).toBe("Analyze the release blockers.");
    expect(result.state.analyzerOutput).toBe("Nested workflow analysis complete.");
  });

  it("fails sub_workflow steps when the referenced team is not registered", async () => {
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "nested",
          agent: "research_team",
          type: "sub_workflow",
          team: "missing_team"
        }
      ]
    });

    const result = await workflow.execute({
      agents: {},
      initialState: { task: "Plan the work." }
    });

    expect(result.status).toBe("failed");
    expect(result.error).toContain("missing_team");
  });

  it("pauses sub_workflow steps when nested workflows pause and resumes after nested input", async () => {
    const observedEvents: string[] = [];

    const reviewer = new Agent({
      id: "reviewer",
      role: "Reviewer",
      instructions: "Pause for approval before publication.",
      model: createMockModel("mock-subworkflow-nested-reviewer", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const publisher = new Agent({
      id: "publisher",
      role: "Publisher",
      instructions: "Publish the approved launch brief.",
      model: createMockModel("mock-subworkflow-nested-publisher", () => ({
        text: "Published the approved launch brief."
      })),
      behavior: "llm_only",
      prompt: (state) => `Approval: ${String(state.reviewDecision ?? "pending")}`
    });

    const nestedWorkflow = new WorkflowEngine({
      steps: [
        {
          id: "review",
          agent: "reviewer",
          type: "human_gate"
        }
      ]
    });
    const workflow = new WorkflowEngine({
      subWorkflows: {
        review_team: {
          workflow: nestedWorkflow,
          agents: { reviewer }
        }
      },
      steps: [
        {
          id: "review-phase",
          agent: "review_team",
          type: "sub_workflow",
          team: "review_team",
          outputMapping: {
            reviewDecision: "reviewerOutput"
          },
          next: "publish"
        },
        {
          id: "publish",
          agent: "publisher",
          type: "sequential"
        }
      ]
    });

    workflow.onEvent((event) => {
      observedEvents.push(`${event.type}:${event.stepId}:${event.agentId}`);
    });

    const paused = await workflow.execute({
      agents: { publisher },
      initialState: { task: "Approve the launch brief for publication." }
    });

    expect(paused.status).toBe("paused");
    expect(paused.pendingHumanInput).toEqual({
      stepId: "review",
      agentId: "reviewer",
      prompt: "Agent 'Reviewer' requires your input."
    });
    expect(paused.pauseContext).toMatchObject({
      stepId: "review-phase",
      agentId: "review_team",
      reason: "human_gate",
      subWorkflow: {
        team: "review_team",
        pausedResult: {
          status: "paused",
          pendingHumanInput: {
            stepId: "review",
            agentId: "reviewer",
            prompt: "Agent 'Reviewer' requires your input."
          },
          pauseContext: {
            stepId: "review",
            agentId: "reviewer",
            reason: "human_gate"
          }
        }
      }
    });
    expect(paused.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "review-phase:paused"
    ]);
    expect(observedEvents).toEqual([
      "step_start:review-phase:review_team",
      "step_start:review:reviewer",
      "human_requested:review:reviewer"
    ]);

    const resumed = await workflow.resume({
      agents: { publisher },
      pausedResult: paused,
      responses: { humanInput: "Approved for publication." }
    });

    expect(resumed.status).toBe("completed");
    expect(resumed.state.reviewDecision).toBe("Approved for publication.");
    expect(resumed.state.publisherOutput).toBe("Published the approved launch brief.");
    expect(resumed.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "review-phase:paused",
      "review-phase:completed",
      "publish:completed"
    ]);
    expect(observedEvents).toContain("approval:review:reviewer");
    expect(observedEvents).toContain("step_complete:review-phase:review_team");
    expect(observedEvents).toContain("step_start:publish:publisher");
  });
});

describe("WorkflowSession", () => {
  it("tracks pending requests when a workflow pauses", async () => {
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model: createMockModel("mock-session-human-gate", () => ({ text: "unused" })),
      behavior: "human_gate"
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate"
        }
      ]
    });
    const session = new WorkflowSession({
      workflow,
      agents: { approver },
      initialState: { task: "Approve the release candidate." }
    });

    await session.run();

    expect(session.status).toBe("paused");
    expect(session.result?.status).toBe("paused");
    expect(session.pendingRequests).toHaveLength(1);
    expect(session.pendingRequests[0]).toMatchObject({
      requestType: "human_gate",
      agentId: "approver",
      stepId: "request-approval",
      context: {
        prompt: "Agent 'Human Approver' requires your input."
      }
    });
  });

  it("surfaces action approval requests through the session API", async () => {
    const deployer = new Agent({
      id: "deployer",
      role: "Deployer",
      instructions: "Plan a deployment action and wait for approval.",
      model: createMockModel("mock-session-action-approval", () => ({
        text: "Deploy the release to staging after approval.",
        toolCalls: [
          {
            id: "call-session-deploy",
            name: "deploy_release",
            input: {
              environment: "staging",
              version: "2026.03.06"
            }
          }
        ]
      })),
      behavior: "action_executor",
      actionPolicy: "require_approval",
      tools: {
        deploy_release: {
          description: "Deploy a release to the requested environment.",
          inputSchema: z.object({
            environment: z.string(),
            version: z.string()
          }),
          execute: async (input) => input
        }
      }
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential"
        }
      ]
    });
    const session = new WorkflowSession({
      workflow,
      agents: { deployer },
      initialState: { task: "Deploy the release candidate." }
    });

    await session.run();

    expect(session.status).toBe("paused");
    expect(session.pendingRequests).toHaveLength(1);
    expect(session.pendingRequests[0]).toMatchObject({
      requestType: "action_approval",
      agentId: "deployer",
      stepId: "deploy",
      context: {
        policy: "require_approval",
        output: "Deploy the release to staging after approval.",
        proposedActions: [
          {
            tool: "deploy_release",
            arguments: {
              environment: "staging",
              version: "2026.03.06"
            },
            toolCallId: "call-session-deploy"
          }
        ]
      }
    });
  });

  it("surfaces action error requests through the session API", async () => {
    const deployer = new Agent({
      id: "deployer",
      role: "Deployer",
      instructions: "Execute the rollout and pause only if the action fails.",
      model: createMockModel("mock-session-action-error", () => ({
        text: "Deploy the release and notify operators.",
        toolCalls: [
          {
            id: "call-session-action-error",
            name: "notify_release",
            input: {
              channel: "ops",
              version: "2026.03.06"
            }
          }
        ]
      })),
      behavior: "action_executor",
      actionPolicy: "confirm_on_error",
      rollbackOnFailure: true,
      rollbackAction: "rollback_deploy",
      tools: {
        notify_release: {
          description: "Send the deployment notification.",
          inputSchema: z.object({
            channel: z.string(),
            version: z.string()
          }),
          execute: async () => {
            throw new Error("Notification delivery failed.");
          }
        },
        rollback_deploy: {
          description: "Rollback the failed deployment action.",
          inputSchema: z.object({
            agentId: z.string(),
            failedActions: z.array(z.unknown()),
            actionRecords: z.array(z.unknown())
          }),
          execute: async () => ({
            ok: true,
            recovered: true
          })
        }
      }
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "deploy",
          agent: "deployer",
          type: "sequential"
        }
      ]
    });
    const session = new WorkflowSession({
      workflow,
      agents: { deployer },
      initialState: { task: "Deploy the release candidate." }
    });

    await session.run();

    expect(session.status).toBe("paused");
    expect(session.pendingRequests).toHaveLength(1);
    expect(session.pendingRequests[0]).toMatchObject({
      requestType: "action_error",
      agentId: "deployer",
      stepId: "deploy",
      context: {
        policy: "confirm_on_error",
        output: "Deploy the release and notify operators.",
        failedActions: [
          {
            actionId: "call-session-action-error",
            tool: "notify_release",
            arguments: {
              channel: "ops",
              version: "2026.03.06"
            },
            status: "error",
            policy: "confirm_on_error",
            toolCallId: "call-session-action-error",
            reversible: true,
            rollbackAction: "rollback_deploy",
            result: {
              error: "Notification delivery failed."
            }
          }
        ],
        rollbackRecord: {
          rollbackId: "deployer:rollback:call-session-action-error",
          rollbackAction: "rollback_deploy",
          status: "completed",
          failedActions: [
            {
              actionId: "call-session-action-error",
              tool: "notify_release",
              arguments: {
                channel: "ops",
                version: "2026.03.06"
              },
              status: "error",
              policy: "confirm_on_error",
              toolCallId: "call-session-action-error",
              reversible: true,
              rollbackAction: "rollback_deploy",
              result: {
                error: "Notification delivery failed."
              }
            }
          ],
          result: {
            ok: true,
            recovered: true
          }
        }
      }
    });
  });

  it("resumes through session state transitions", async () => {
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model: createMockModel("mock-session-resume-approver", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write the approved release note.",
      model: createMockModel("mock-session-resume-writer", () => ({
        text: "Session resumed and release note published."
      })),
      behavior: "llm_only",
      prompt: (state) => `Approval: ${String(state.approverOutput ?? "pending")}`
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate",
          next: "publish"
        },
        {
          id: "publish",
          agent: "writer",
          type: "sequential"
        }
      ]
    });
    const hiveflow = new HiveFlow();
    const session = hiveflow.createSession({
      workflow,
      agents: { approver, writer },
      initialState: { task: "Approve and publish the release note." }
    });

    await session.run();
    expect(session.status).toBe("paused");

    await session.resume({ humanInput: "approved" });

    expect(session.status).toBe("completed");
    expect(session.pendingRequests).toEqual([]);
    expect(session.result?.state.approverOutput).toBe("approved");
    expect(session.result?.state.writerOutput).toBe(
      "Session resumed and release note published."
    );
  });

  it("loads a paused session from checkpoint storage and resumes in a fresh HiveFlow instance", async () => {
    const checkpointStorage = new InMemoryCheckpointStorage();
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model: createMockModel("mock-session-checkpoint-approver", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write the approved release note.",
      model: createMockModel("mock-session-checkpoint-writer", () => ({
        text: "Checkpoint-backed session resumed and completed."
      })),
      behavior: "llm_only"
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate",
          next: "publish"
        },
        {
          id: "publish",
          agent: "writer",
          type: "sequential"
        }
      ]
    });

    const hiveflow = new HiveFlow({ checkpointStorage });
    const pausedSession = await hiveflow.runSession({
      workflow,
      agents: { approver, writer },
      initialState: { task: "Approve and publish the release note." }
    });

    expect(pausedSession.status).toBe("paused");
    expect(pausedSession.checkpointId).toBeTruthy();

    const restoredHiveflow = new HiveFlow({ checkpointStorage });
    const restoredSession = await restoredHiveflow.loadSession({
      workflow,
      agents: { approver, writer },
      sessionId: pausedSession.sessionId
    });

    expect(restoredSession.status).toBe("paused");
    expect(restoredSession.pendingRequests).toHaveLength(1);

    const resumedSession = await restoredHiveflow.resumeSession({
      workflow,
      agents: { approver, writer },
      sessionId: pausedSession.sessionId,
      responses: { humanInput: "approved" }
    });

    expect(resumedSession.status).toBe("completed");
    expect(resumedSession.result?.state.approverOutput).toBe("approved");
    expect(resumedSession.result?.state.writerOutput).toBe(
      "Checkpoint-backed session resumed and completed."
    );
  });

  it("loads paused nested sub_workflow sessions from checkpoint storage and resumes them", async () => {
    const checkpointStorage = new InMemoryCheckpointStorage();
    const reviewer = new Agent({
      id: "reviewer",
      role: "Reviewer",
      instructions: "Pause for approval before publication.",
      model: createMockModel("mock-subworkflow-session-reviewer", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const publisher = new Agent({
      id: "publisher",
      role: "Publisher",
      instructions: "Publish the approved launch brief.",
      model: createMockModel("mock-subworkflow-session-publisher", () => ({
        text: "Checkpoint-backed nested workflow resumed and published."
      })),
      behavior: "llm_only",
      prompt: (state) => `Approval: ${String(state.reviewDecision ?? "pending")}`
    });
    const nestedWorkflow = new WorkflowEngine({
      steps: [
        {
          id: "review",
          agent: "reviewer",
          type: "human_gate"
        }
      ]
    });
    const workflow = new WorkflowEngine({
      subWorkflows: {
        review_team: {
          workflow: nestedWorkflow,
          agents: { reviewer }
        }
      },
      steps: [
        {
          id: "review-phase",
          agent: "review_team",
          type: "sub_workflow",
          team: "review_team",
          outputMapping: {
            reviewDecision: "reviewerOutput"
          },
          next: "publish"
        },
        {
          id: "publish",
          agent: "publisher",
          type: "sequential"
        }
      ]
    });

    const hiveflow = new HiveFlow({ checkpointStorage });
    const pausedSession = await hiveflow.runSession({
      workflow,
      agents: { publisher },
      initialState: { task: "Approve the launch brief for publication." }
    });

    expect(pausedSession.status).toBe("paused");
    expect(pausedSession.pendingRequests).toHaveLength(1);
    expect(pausedSession.pendingRequests[0]).toMatchObject({
      requestType: "human_gate",
      agentId: "reviewer",
      stepId: "review",
      context: {
        prompt: "Agent 'Reviewer' requires your input."
      }
    });

    const restoredHiveflow = new HiveFlow({ checkpointStorage });
    const restoredSession = await restoredHiveflow.loadSession({
      workflow,
      agents: { publisher },
      sessionId: pausedSession.sessionId
    });

    expect(restoredSession.status).toBe("paused");
    expect(restoredSession.pendingRequests).toHaveLength(1);
    expect(restoredSession.pendingRequests[0]).toMatchObject({
      requestType: "human_gate",
      agentId: "reviewer",
      stepId: "review"
    });

    const resumedSession = await restoredHiveflow.resumeSession({
      workflow,
      agents: { publisher },
      sessionId: pausedSession.sessionId,
      responses: { humanInput: "Approved for publication." }
    });

    expect(resumedSession.status).toBe("completed");
    expect(resumedSession.result?.state.reviewDecision).toBe("Approved for publication.");
    expect(resumedSession.result?.state.publisherOutput).toBe(
      "Checkpoint-backed nested workflow resumed and published."
    );
    expect(resumedSession.result?.stepResults.map((step) => `${step.stepId}:${step.status}`)).toEqual([
      "review-phase:paused",
      "review-phase:completed",
      "publish:completed"
    ]);
  });

  it("rebuilds paused sessions from checkpointed workflow definitions", async () => {
    const checkpointStorage = new InMemoryCheckpointStorage();
    const runtimeCatalog = createDefinitionRuntimeCatalog();
    const definition: WorkflowDefinition = {
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate",
          next: "publish"
        },
        {
          id: "publish",
          agent: "writer",
          type: "sequential"
        }
      ],
      agents: [
        {
          id: "approver",
          role: "Human Approver",
          instructions: "Request human approval before continuing.",
          behavior: "human_gate",
          model: {
            kind: "mock",
            options: {
              id: "mock-definition-approver",
              responses: [{ text: "unused" }]
            }
          }
        },
        {
          id: "writer",
          role: "Writer",
          instructions: "Write the approved release note.",
          behavior: "llm_only",
          model: {
            kind: "mock",
            options: {
              id: "mock-definition-writer",
              responses: [
                {
                  text: "Definition-backed checkpoint resumed without rebuilding runtime manually."
                }
              ]
            }
          }
        }
      ]
    };

    const hiveflow = new HiveFlow({ checkpointStorage, runtimeCatalog });
    const pausedSession = await hiveflow.runSessionFromDefinition({
      definition,
      initialState: { task: "Approve and publish the release note." }
    });

    const checkpoint = await checkpointStorage.load(pausedSession.sessionId);

    expect(pausedSession.status).toBe("paused");
    expect(checkpoint?.workflowDefinition).toEqual(definition);

    const restoredHiveflow = new HiveFlow({ checkpointStorage, runtimeCatalog });
    const restoredSession = await restoredHiveflow.loadSession({
      sessionId: pausedSession.sessionId
    });

    expect(restoredSession.status).toBe("paused");
    expect(restoredSession.pendingRequests).toHaveLength(1);

    const resumedSession = await restoredHiveflow.resumeSession({
      sessionId: pausedSession.sessionId,
      responses: { humanInput: "approved" }
    });

    expect(resumedSession.status).toBe("completed");
    expect(resumedSession.result?.state.approverOutput).toBe("approved");
    expect(resumedSession.result?.state.writerOutput).toBe(
      "Definition-backed checkpoint resumed without rebuilding runtime manually."
    );
  });

  it("requires manual runtime for checkpoints without stored workflow definitions", async () => {
    const checkpointStorage = new InMemoryCheckpointStorage();
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model: createMockModel("mock-legacy-checkpoint-approver", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate"
        }
      ]
    });

    const hiveflow = new HiveFlow({ checkpointStorage });
    const pausedSession = await hiveflow.runSession({
      workflow,
      agents: { approver },
      initialState: { task: "Approve the release candidate." }
    });

    const restoredHiveflow = new HiveFlow({ checkpointStorage });

    await expect(
      restoredHiveflow.loadSession({
        sessionId: pausedSession.sessionId
      })
    ).rejects.toThrow("does not contain a workflow definition");
  });

  it("persists checkpoints to the filesystem", async () => {
    const directory = await mkdtemp(join(tmpdir(), "hiveflow-js-checkpoint-test-"));

    try {
      const checkpointStorage = new FileCheckpointStorage(directory);
      const approver = new Agent({
        id: "approver",
        role: "Human Approver",
        instructions: "Request human approval before continuing.",
        model: createMockModel("mock-file-checkpoint-approver", () => ({ text: "unused" })),
        behavior: "human_gate"
      });
      const workflow = new WorkflowEngine({
        steps: [
          {
            id: "request-approval",
            agent: "approver",
            type: "human_gate"
          }
        ]
      });
      const session = new WorkflowSession({
        workflow,
        agents: { approver },
        checkpointStorage,
        initialState: { task: "Approve the release candidate." },
        sessionId: "file-checkpoint-session"
      });

      await session.run();

      const loadedCheckpoint = await checkpointStorage.load(session.sessionId);
      const sessionIds = await checkpointStorage.listSessions();
      const checkpoints = await checkpointStorage.listCheckpoints(session.sessionId);

      expect(session.status).toBe("paused");
      expect(loadedCheckpoint?.checkpointId).toBe(session.checkpointId);
      expect(loadedCheckpoint?.pausedResult.status).toBe("paused");
      expect(sessionIds).toEqual([session.sessionId]);
      expect(checkpoints).toHaveLength(1);

      await checkpointStorage.delete(session.sessionId);

      expect(await checkpointStorage.load(session.sessionId)).toBeUndefined();
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("streams workflow events through the session lifecycle", async () => {
    const approver = new Agent({
      id: "approver",
      role: "Human Approver",
      instructions: "Request human approval before continuing.",
      model: createMockModel("mock-session-events-approver", () => ({ text: "unused" })),
      behavior: "human_gate"
    });
    const writer = new Agent({
      id: "writer",
      role: "Writer",
      instructions: "Write the approved release note.",
      model: createMockModel("mock-session-events-writer", () => ({
        text: "Event stream completed after approval."
      })),
      behavior: "llm_only"
    });

    const workflow = new WorkflowEngine({
      steps: [
        {
          id: "request-approval",
          agent: "approver",
          type: "human_gate",
          next: "publish"
        },
        {
          id: "publish",
          agent: "writer",
          type: "sequential"
        }
      ]
    });
    const session = new WorkflowSession({
      workflow,
      agents: { approver, writer },
      initialState: { task: "Approve and publish the release note." }
    });
    const consumer = session.events();
    const eventTask = collectSessionEvents(consumer);

    await session.run();
    await session.resume({ humanInput: "approved" });

    const events = await eventTask;

    expect(events.map((event) => event.type)).toEqual([
      "step_start",
      "human_requested",
      "approval",
      "step_start",
      "step_complete"
    ]);
    expect(events[0]).toMatchObject({
      type: "step_start",
      stepId: "request-approval",
      agentId: "approver"
    });
    expect(events[1]).toMatchObject({
      type: "human_requested",
      stepId: "request-approval",
      agentId: "approver",
      prompt: "Agent 'Human Approver' requires your input."
    });
    expect(events[2]).toMatchObject({
      type: "approval",
      stepId: "request-approval",
      agentId: "approver"
    });
    expect(events[3]).toMatchObject({
      type: "step_start",
      stepId: "publish",
      agentId: "writer"
    });
    expect(events[4]).toMatchObject({
      type: "step_complete",
      stepId: "publish",
      agentId: "writer"
    });
  });
});

async function collectSessionEvents(
  consumer: AsyncIterable<{
    type: string;
    stepId: string;
    agentId: string;
    prompt?: string;
  }>
): Promise<Array<{ type: string; stepId: string; agentId: string; prompt?: string }>> {
  const events = [] as Array<{ type: string; stepId: string; agentId: string; prompt?: string }>;
  for await (const event of consumer) {
    events.push(event);
  }
  return events;
}