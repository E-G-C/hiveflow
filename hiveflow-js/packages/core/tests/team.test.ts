import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ArchetypeLibrary,
  HiveFlow,
  InMemoryCheckpointStorage,
  TeamConfiguration,
  TeamGenerator,
  TeamLibrary,
  WorkflowRuntimeCatalog,
  createMockModel
} from "../src/index.js";
import type { MockModelResponse } from "../src/index.js";

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
      },
      named: (definition) =>
        createMockModel(String(definition.options?.reference ?? "named-model"), () => ({
          text: "Named model placeholder output."
        }))
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

describe("TeamConfiguration", () => {
  it("round-trips JSON and YAML team configuration files", async () => {
    const directory = await mkdtemp(join(tmpdir(), "hiveflow-js-team-config-"));

    try {
      const configuration = new TeamConfiguration({
        teamName: "release_notes",
        version: "1.0",
        description: "Generate and publish release notes.",
        agents: [
          {
            id: "researcher",
            role: "Researcher",
            instructions: "Collect release highlights.",
            behavior: "llm_only",
            model: {
              kind: "mock",
              options: {
                id: "mock-team-config-researcher",
                responses: [{ text: "Collected the key release highlights." }]
              }
            }
          }
        ],
        workflow: {
          steps: [
            {
              agent: "researcher",
              type: "sequential"
            }
          ]
        }
      });
      const jsonPath = join(directory, "release_notes.json");
      const yamlPath = join(directory, "release_notes.yaml");

      await configuration.saveJson(jsonPath);
      await configuration.saveYaml(yamlPath);

      const fromJson = await TeamConfiguration.fromJsonFile(jsonPath);
      const fromYaml = await TeamConfiguration.fromYamlFile(yamlPath);

      expect(fromJson.toJSON()).toEqual(configuration.toJSON());
      expect(fromYaml.toJSON()).toEqual(configuration.toJSON());
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("resolves library-backed sub-workflows when compiling workflow definitions", () => {
    const subWorkflow = new TeamConfiguration({
      teamName: "deep_research",
      agents: [
        {
          id: "researcher",
          role: "Researcher",
          instructions: "Produce concise findings.",
          behavior: "llm_only",
          model: {
            kind: "mock",
            options: {
              id: "mock-team-subworkflow-researcher",
              responses: [{ text: "Sub-workflow findings." }]
            }
          }
        }
      ],
      workflow: {
        steps: [
          {
            agent: "researcher",
            type: "sequential"
          }
        ]
      }
    });
    const parent = new TeamConfiguration({
      teamName: "parent_workflow",
      agents: [
        {
          id: "writer",
          role: "Writer",
          instructions: "Summarize the findings.",
          behavior: "llm_only",
          model: {
            kind: "mock",
            options: {
              id: "mock-team-parent-writer",
              responses: [{ text: "Published the research summary." }]
            }
          }
        }
      ],
      workflow: {
        steps: [
          {
            agent: "research_team",
            type: "sub_workflow",
            team: "deep_research",
            outputMapping: {
              findings: "researcherOutput"
            },
            next: "writer"
          },
          {
            agent: "writer",
            type: "sequential"
          }
        ]
      }
    });
    const library = new TeamLibrary().register("deep_research", subWorkflow);

    const definition = parent.toWorkflowDefinition({ teamLibrary: library });

    expect(definition.steps.map((step) => step.id)).toEqual(["research_team", "writer"]);
    expect(definition.steps[0]).toMatchObject({
      type: "sub_workflow",
      team: "deep_research",
      next: "writer"
    });
    expect(definition.subWorkflows?.deep_research?.steps[0].id).toBe("researcher");
  });

  it("resolves string model references with a supplied resolver", () => {
    const configuration = new TeamConfiguration({
      team_name: "string_models",
      agents: [
        {
          id: "planner",
          role: "Planner",
          system_prompt: "Plan the work.",
          behavior_type: "orchestrator",
          model: "strategic-llm"
        }
      ],
      workflow: {
        steps: [
          {
            agent: "planner",
            type: "sequential"
          }
        ]
      }
    });

    const definition = configuration.toWorkflowDefinition({
      modelResolver: (reference) => ({
        kind: "named",
        options: {
          reference
        }
      })
    });

    expect(definition.agents[0].model).toEqual({
      kind: "named",
      options: {
        reference: "strategic-llm"
      }
    });
  });

  it("preserves collaboration config when compiling workflow definitions", () => {
    const configuration = new TeamConfiguration({
      teamName: "adaptive_team",
      collaboration: {
        enabled: true,
        maxDelegationDepth: 2,
        maxSpawnedAgents: 4,
        allowRecursiveOrchestrators: false,
        delegationTimeoutSeconds: 45,
        budgetPolicy: "inherit_parent"
      },
      agents: [
        {
          id: "coordinator",
          role: "Coordinator",
          instructions: "Coordinate sub-tasks dynamically.",
          behavior: "orchestrator",
          model: {
            kind: "mock",
            options: {
              id: "mock-adaptive-team",
              responses: [{ text: "Coordinated output." }]
            }
          }
        }
      ],
      workflow: {
        steps: [
          {
            agent: "coordinator",
            type: "sequential"
          }
        ]
      }
    });

    const definition = configuration.toWorkflowDefinition();

    expect(configuration.toJSON()).toMatchObject({
      collaboration: {
        enabled: true,
        maxDelegationDepth: 2,
        maxSpawnedAgents: 4,
        allowRecursiveOrchestrators: false,
        delegationTimeoutSeconds: 45,
        budgetPolicy: "inherit_parent"
      }
    });
    expect(definition.collaboration).toEqual({
      enabled: true,
      maxDelegationDepth: 2,
      maxSpawnedAgents: 4,
      allowRecursiveOrchestrators: false,
      delegationTimeoutSeconds: 45,
      budgetPolicy: "inherit_parent"
    });
  });
});

describe("TeamLibrary", () => {
  it("loads JSON and YAML teams from a directory and exposes built-in templates", async () => {
    const directory = await mkdtemp(join(tmpdir(), "hiveflow-js-team-library-"));

    try {
      const jsonConfig = new TeamConfiguration({
        teamName: "json_team",
        agents: [
          {
            id: "writer",
            role: "Writer",
            instructions: "Write the summary.",
            behavior: "llm_only",
            model: {
              kind: "mock",
              options: {
                id: "mock-team-library-json",
                responses: [{ text: "JSON team output." }]
              }
            }
          }
        ],
        workflow: {
          steps: [
            {
              agent: "writer",
              type: "sequential"
            }
          ]
        }
      });
      const yamlConfig = new TeamConfiguration({
        teamName: "yaml_team",
        agents: [
          {
            id: "reviewer",
            role: "Reviewer",
            instructions: "Review the summary.",
            behavior: "llm_only",
            model: {
              kind: "mock",
              options: {
                id: "mock-team-library-yaml",
                responses: [{ text: "YAML team output." }]
              }
            }
          }
        ],
        workflow: {
          steps: [
            {
              agent: "reviewer",
              type: "sequential"
            }
          ]
        }
      });

      await jsonConfig.saveJson(join(directory, "json_team.json"));
      await yamlConfig.saveYaml(join(directory, "yaml_team.yaml"));

      const library = await TeamLibrary.fromDirectory(directory);
      const defaultLibrary = await TeamLibrary.default();

      expect(library.listTeams()).toEqual(["json_team", "yaml_team"]);
      expect(library.get("json_team")?.teamName).toBe("json_team");
      expect(defaultLibrary.listTeams()).toContain("research_report");
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

describe("ArchetypeLibrary", () => {
  it("loads JSON and YAML archetypes from a directory and exposes built-in archetypes", async () => {
    const directory = await mkdtemp(join(tmpdir(), "hiveflow-js-archetype-library-"));

    try {
      await writeFile(
        join(directory, "analyst.json"),
        JSON.stringify(
          {
            id: "analyst",
            role: "Analyst",
            instructions: "Analyze the findings.",
            behavior: "llm_only"
          },
          null,
          2
        ),
        "utf8"
      );
      await writeFile(
        join(directory, "editor.yaml"),
        [
          "id: editor",
          "role: Editor",
          'instructions: "Refine the final answer."',
          "behavior: llm_only"
        ].join("\n"),
        "utf8"
      );

      const library = await ArchetypeLibrary.fromDirectory(directory);
      const defaultLibrary = await ArchetypeLibrary.default();

      expect(library.listArchetypes()).toEqual(["analyst", "editor"]);
      expect(library.get("analyst")).toMatchObject({
        id: "analyst",
        role: "Analyst"
      });
      expect(defaultLibrary.listArchetypes()).toContain("writer");
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

describe("TeamGenerator", () => {
  it("generates self-contained teams from archetypes with deterministic review flow", () => {
    const generator = new TeamGenerator({
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns()
    });

    const team = generator.generateTeam({
      taskDescription: "Publish release notes for the deployment.",
      archetypes: ["writer"],
      model: "editorial-model"
    });

    expect(team.toJSON()).toMatchObject({
      teamName: "Generated Team: Publish release notes for the deployment.",
      description: "Publish release notes for the deployment.",
      agents: [
        {
          id: "writer",
          model: "editorial-model"
        },
        {
          id: "reviewer",
          model: "editorial-model"
        }
      ],
      workflow: {
        steps: [
          {
            agent: "writer",
            type: "sequential",
            next: "reviewer"
          },
          {
            agent: "reviewer",
            type: "conditional",
            nextOnReject: "writer"
          }
        ]
      }
    });
  });

  it("generates teams from LLM output and reports capability gaps plus new archetypes", async () => {
    const generator = new TeamGenerator({
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns()
    });
    const llm = createMockModel("mock-llm-team-generation", () => ({
      text: [
        "```json",
        JSON.stringify(
          {
            teamName: "Generated Team: Market Brief",
            description: "Prepare a fact-checked market brief.",
            agents: [
              {
                id: "analyst",
                role: "Analyst",
                instructions: "Analyze the collected material and produce structured notes.",
                behavior: "tool_user",
                toolIds: ["spreadsheet_lookup"],
                model: "$SMART_LLM"
              },
              {
                id: "writer",
                role: "Writer",
                instructions: "Turn the analysis into a concise market brief.",
                behavior: "llm_only",
                model: "$SMART_LLM"
              }
            ],
            workflow: {
              steps: [
                {
                  agent: "analyst",
                  type: "sequential",
                  next: "writer"
                },
                {
                  agent: "writer",
                  type: "sequential"
                }
              ]
            }
          },
          null,
          2
        ),
        "```"
      ].join("\n")
    }));

    const result = await generator.generateTeamFromLLM({
      taskDescription: "Prepare a fact-checked market brief.",
      llm,
      availableTools: ["web_search"]
    });

    expect(result.config).toBeInstanceOf(TeamConfiguration);
    expect(result.config.toJSON()).toMatchObject({
      teamName: "Generated Team: Market Brief",
      description: "Prepare a fact-checked market brief.",
      agents: [
        {
          id: "analyst",
          toolIds: ["spreadsheet_lookup"]
        },
        {
          id: "writer"
        }
      ]
    });
    expect(result.capabilityGaps).toEqual([
      {
        resourceType: "tool",
        resourceId: "spreadsheet_lookup",
        severity: "blocking",
        description: "Agent 'analyst' requires tool 'spreadsheet_lookup' which is not registered",
        fallbackStrategy: "Remove tool requirement or register 'spreadsheet_lookup'"
      }
    ]);
    expect(result.newArchetypes).toEqual([
      {
        id: "analyst",
        role: "Analyst",
        instructions: "Analyze the collected material and produce structured notes.",
        model: "$SMART_LLM",
        behavior: "tool_user",
        toolIds: ["spreadsheet_lookup"]
      }
    ]);
    expect(result.hasBlockingGaps).toBe(true);
  });

  it("retries invalid LLM team output with validation feedback", async () => {
    const generator = new TeamGenerator({
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns()
    });
    let repairRequestSeen = false;

    const llm = createMockModel("mock-llm-team-generation-retry", (request, callIndex) => {
      if (callIndex === 0) {
        return {
          text: JSON.stringify({
            teamName: "Generated Team: Research Brief",
            description: "Prepare a fact-checked market brief.",
            agents: [
              {
                id: "researcher",
                role: "Researcher",
                instructions: "Collect source-backed findings.",
                behavior: "tool_user",
                toolIds: ["web_search"],
                model: "$SMART_LLM"
              }
            ],
            workflow: {
              steps: [
                {
                  type: "sequential"
                }
              ]
            }
          })
        };
      }

      repairRequestSeen = request.messages.some(
        (message) =>
          message.role === "user" &&
          message.content.includes("The previous TeamConfiguration response was invalid.")
      );

      return {
        output: {
          teamName: "Generated Team: Research Brief",
          description: "Prepare a fact-checked market brief.",
          agents: [
            {
              id: "researcher",
              role: "Researcher",
              instructions: "Collect source-backed findings.",
              behavior: "tool_user",
              toolIds: ["web_search"],
              model: "$SMART_LLM"
            },
            {
              id: "writer",
              role: "Writer",
              instructions: "Draft the brief from the findings.",
              behavior: "llm_only",
              model: "$SMART_LLM"
            }
          ],
          workflow: {
            steps: [
              {
                agent: "researcher",
                type: "sequential",
                next: "writer"
              },
              {
                agent: "writer",
                type: "sequential"
              }
            ]
          }
        }
      };
    });

    const result = await generator.generateTeamFromLLM({
      taskDescription: "Prepare a fact-checked market brief.",
      llm,
      availableTools: ["web_search"]
    });

    expect(repairRequestSeen).toBe(true);
    expect(result.config.toJSON()).toMatchObject({
      teamName: "Generated Team: Research Brief",
      workflow: {
        steps: [
          {
            agent: "researcher",
            type: "sequential"
          },
          {
            agent: "writer",
            type: "sequential"
          }
        ]
      }
    });
  });

  it("rejects auto-approval when LLM-generated teams contain blocking gaps", async () => {
    const generator = new TeamGenerator({
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns()
    });
    const llm = createMockModel("mock-llm-team-generation-auto-approve", () => ({
      text: JSON.stringify({
        teamName: "Generated Team: Release Review",
        description: "Review the release package.",
        agents: [
          {
            id: "analyst",
            role: "Analyst",
            instructions: "Inspect the release package.",
            behavior: "tool_user",
            toolIds: ["package_inspector"],
            model: "$SMART_LLM"
          }
        ],
        workflow: {
          steps: [
            {
              agent: "analyst",
              type: "sequential"
            }
          ]
        }
      })
    }));

    await expect(
      generator.generateTeamFromLLM({
        taskDescription: "Review the release package.",
        llm,
        availableTools: ["web_search"],
        autoApprove: true
      })
    ).rejects.toThrow(
      "Cannot auto-approve team with blocking gaps: tool:package_inspector (blocking)"
    );
  });

  it("exposes LLM team generation through the HiveFlow facade", async () => {
    const hiveflow = new HiveFlow({
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns()
    });
    const llm = createMockModel("mock-hiveflow-llm-team-generation", () => ({
      output: {
        teamName: "Generated Team: Research Brief",
        description: "Publish a concise research brief.",
        agents: [
          {
            id: "researcher",
            role: "Researcher",
            instructions: "Collect source-backed findings.",
            behavior: "tool_user",
            toolIds: ["web_search"],
            model: "$SMART_LLM"
          },
          {
            id: "writer",
            role: "Writer",
            instructions: "Draft the brief from the findings.",
            behavior: "llm_only",
            model: "$SMART_LLM"
          },
          {
            id: "reviewer",
            role: "Reviewer",
            instructions: "Review the draft for accuracy and clarity.",
            behavior: "llm_only",
            model: "$SMART_LLM"
          }
        ],
        workflow: {
          steps: [
            {
              agent: "researcher",
              type: "sequential",
              next: "writer"
            },
            {
              agent: "writer",
              type: "sequential",
              next: "reviewer"
            },
            {
              agent: "reviewer",
              type: "conditional",
              nextOnReject: "writer"
            }
          ]
        }
      }
    }));

    const result = await hiveflow.composeTeamFromLLM({
      taskDescription: "Publish a concise research brief.",
      llm,
      availableTools: ["web_search"]
    });

    expect(result.hasBlockingGaps).toBe(false);
    expect(result.capabilityGaps).toEqual([]);
    expect(result.newArchetypes).toEqual([]);
    expect(result.config.toJSON()).toMatchObject({
      teamName: "Generated Team: Research Brief",
      workflow: {
        steps: [
          {
            agent: "researcher",
            next: "writer"
          },
          {
            agent: "writer",
            next: "reviewer"
          },
          {
            agent: "reviewer",
            nextOnReject: "writer"
          }
        ]
      }
    });
  });
});

describe("HiveFlow team APIs", () => {
  it("runs and resumes sessions built from team configurations and team libraries", async () => {
    const checkpointStorage = new InMemoryCheckpointStorage();
    const runtimeCatalog = createDefinitionRuntimeCatalog();
    const library = new TeamLibrary();
    const team = new TeamConfiguration({
      teamName: "approval_flow",
      agents: [
        {
          id: "approver",
          role: "Approver",
          instructions: "Pause for human approval.",
          behavior: "human_gate",
          model: {
            kind: "mock",
            options: {
              id: "mock-team-api-approver",
              responses: [{ text: "unused" }]
            }
          }
        },
        {
          id: "writer",
          role: "Writer",
          instructions: "Write the approved summary.",
          behavior: "llm_only",
          model: {
            kind: "mock",
            options: {
              id: "mock-team-api-writer",
              responses: [{ text: "Team-config session resumed and published." }]
            }
          }
        }
      ],
      workflow: {
        steps: [
          {
            agent: "approver",
            type: "human_gate",
            next: "writer"
          },
          {
            agent: "writer",
            type: "sequential"
          }
        ]
      }
    });
    library.register(team.teamName, team);

    const hiveflow = new HiveFlow({ checkpointStorage, runtimeCatalog, teamLibrary: library });
    const pausedSession = await hiveflow.runSessionFromTeam({
      team: "approval_flow",
      initialState: { task: "Approve and publish the deployment summary." }
    });

    expect(pausedSession.status).toBe("paused");
    expect(pausedSession.pendingRequests[0]).toMatchObject({
      requestType: "human_gate",
      agentId: "approver"
    });

    const restoredSession = await hiveflow.resumeSession({
      sessionId: pausedSession.sessionId,
      responses: { humanInput: "approved" }
    });

    expect(restoredSession.status).toBe("completed");
    expect(restoredSession.result?.state.writerOutput).toBe(
      "Team-config session resumed and published."
    );
    expect(restoredSession.result?.state.approverOutput).toBe("approved");
  });

  it("exposes discovery accessors and runs deterministically composed teams", async () => {
    const hiveflow = new HiveFlow({
      runtimeCatalog: createDefinitionRuntimeCatalog(),
      archetypeLibrary: ArchetypeLibrary.fromBuiltIns()
    });
    const generatedTeam = hiveflow.composeTeam({
      taskDescription: "Publish an executive summary.",
      archetypes: ["writer"],
      model: "generator-model"
    });

    const result = await hiveflow.runFromTeam({
      team: generatedTeam,
      initialState: {
        task: "Publish an executive summary."
      },
      modelResolver: (_reference, context) => ({
        kind: "mock",
        options: {
          id: `mock-generated-${context.agentId}`,
          responses: [
            context.agentId === "writer"
              ? { text: "Executive summary drafted." }
              : { text: "accepted" }
          ]
        }
      })
    });

    expect(hiveflow.teamLibrary().listTeams()).toEqual([]);
    expect(hiveflow.archetypeLibrary().listArchetypes()).toContain("writer");
    expect(result.status).toBe("completed");
    expect(result.state.writerOutput).toBe("Executive summary drafted.");
    expect(result.state.reviewerOutput).toBe("accepted");
  });
});